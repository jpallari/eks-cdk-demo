#!/usr/bin/env python3

import re
import argparse
import boto3
import yaml
import kubernetes
import eks_client

_eks_role_type_pattern = re.compile(r'^eks/(\w+)/type$')
_iam_client = boto3.client('iam')
_sts_client = boto3.client('sts')

def get_account_id() -> str:
    return _sts_client.get_caller_identity()['Account']

def fetch_roles():
    paginator = _iam_client.get_paginator('list_roles')
    return paginator.paginate(PathPrefix='/eks/')

def generate_role_mappings(account_id: str, roles_output) -> dict:
    all_mappings = {}

    for roles in roles_output:
        for role in roles.get('Roles', []):
            mappings = create_mappings(account_id, role)
            for cluster, mapping in mappings.items():
                l = all_mappings.get(cluster, [])
                l.append(mapping)
                all_mappings[cluster] = l

    return all_mappings

def create_mappings(account_id: str, role: dict) -> dict:
    arn = 'arn:aws:iam::%s:role/%s' % (account_id, role['RoleName'])
    tags = _iam_client.list_role_tags(
        RoleName=role['RoleName'],
        MaxItems=100,
    ).get('Tags', [])
    tags = {
        tag['Key']: tag['Value']
        for tag in tags
    }
    
    clusters = []
    for key in tags:
        match = _eks_role_type_pattern.match(key)
        if match:
            clusters.append(match[1])
    
    mappings = {}
    for cluster in clusters:
        role_type = tags['eks/%s/type' % cluster]
        if role_type == 'user':
            mappings[cluster] = {
                'rolearn': arn,
                'username': tags['eks/%s/username' % cluster],
                'groups': tags['eks/%s/groups' % cluster].split(',')
            }
        elif role_type == 'node':
            mappings[cluster] = {
                'rolearn': arn,
                'username': 'system:node:{{EC2PrivateDNSName}}',
                'groups': ['system:bootstrappers', 'system:nodes'],
            }
        else:
            raise ValueError('Unexpected role type: %s' % role_type)

    return mappings

def update_aws_auth(role_mappings: dict) -> None:
    for cluster, mappings in role_mappings.items():
        client = eks_client.for_cluster(cluster)
        update_aws_auth_cm(client, mappings)
        print('Updated AWS auth for cluster: ', cluster)

def update_aws_auth_cm(client: kubernetes.client.ApiClient, mappings: dict) -> None:
    v1 = kubernetes.client.CoreV1Api(client)
    body = kubernetes.client.V1ConfigMap(
        metadata={
            'name': 'aws-auth',
        },
        data={
            'mapRoles': yaml.dump(mappings)
        }
    )

    try:
        _ = v1.read_namespaced_config_map(name='aws-auth', namespace='kube-system')
        v1.replace_namespaced_config_map(name='aws-auth', namespace='kube-system', body=body)
    except kubernetes.client.rest.ApiException as e:
        if e.status == 404:
            v1.create_namespaced_config_map(namespace='kube-system', body=body)
        else:
            raise

def print_role_mappings(role_mappings):
    for cluster, mappings in role_mappings.items():
        print('EKS cluster:', cluster)
        print('Role mappings:')
        print(yaml.dump(mappings))
        print('')

def main() -> None:
    aparser = argparse.ArgumentParser(
        description='Update AWS auth in EKS clusters according to the account roles',
    )
    aparser.add_argument(
        '--update',
        dest='update',
        action='store_true',
        help='Update clusters instead of printing the AWS auth details',
    )
    args = aparser.parse_args()

    account_id = get_account_id()
    roles = fetch_roles()
    role_mappings = generate_role_mappings(account_id, roles)
    
    print_role_mappings(role_mappings)
    if args.update:
        update_aws_auth(role_mappings)
    else:
        print('Skipping update')

if __name__ == '__main__':
    main()
