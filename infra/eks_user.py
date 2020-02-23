import typing

from aws_cdk import (
    core,
    aws_eks,
    aws_iam,
)

_eks_node_role_base_policies = (
    aws_iam.ManagedPolicy.from_aws_managed_policy_name('AmazonEKSWorkerNodePolicy'),
    aws_iam.ManagedPolicy.from_aws_managed_policy_name('AmazonEKS_CNI_Policy'),
    aws_iam.ManagedPolicy.from_aws_managed_policy_name('AmazonEC2ContainerRegistryReadOnly'),
)

def eks_user(
    scope: core.Construct,
    id: str,
    role_name: str,
    k8s_username: str,
    k8s_groups: typing.List[str],
    clusters: typing.List[aws_eks.ICluster],
    principal: aws_iam.IPrincipal,
) -> aws_iam.Role:
    cluster_access = aws_iam.PolicyDocument(
        statements=[
            aws_iam.PolicyStatement(
                actions=['eks:DescribeCluster'],
                resources=[cluster.cluster_arn for cluster in clusters],
            )
        ]
    )

    role = aws_iam.Role(
        scope=scope,
        id=id,
        path='/eks/',
        role_name=role_name,
        assumed_by=principal,
        inline_policies={
            'cluster-access': cluster_access
        }
    )

    for cluster in clusters:
        core.Tag.add(
            scope=role,
            key='eks/%s/type' % cluster.cluster_name,
            value='user'
        )
        core.Tag.add(
            scope=role,
            key='eks/%s/username' % cluster.cluster_name,
            value=k8s_username,
        )
        core.Tag.add(
            scope=role,
            key='eks/%s/groups' % cluster.cluster_name,
            value=','.join(k8s_groups),
        )

    return role

def eks_node_role(
    scope: core.Construct,
    id: str,
    role_name: str,
    cluster: aws_eks.ICluster,
) -> aws_iam.Role:
    role = aws_iam.Role(
        scope=scope,
        id=id,
        role_name=role_name,
        path='/eks/',
        assumed_by=aws_iam.ServicePrincipal('ec2.amazonaws.com'),
        managed_policies=list(_eks_node_role_base_policies),
    )

    core.Tag.add(
        scope=role,
        key='eks/%s/type' % cluster.cluster_name,
        value='node'
    )

    return role
