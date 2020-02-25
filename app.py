#!/usr/bin/env python3

import os

from aws_cdk import (
    core,
)

import infra.network
import infra.cluster_users
import infra.eks

app = core.App()
name = os.getenv('ENV_NAME', 'mytest')
cluster_name = name
env = core.Environment(region=os.getenv('AWS_REGION', 'eu-central-1'))
tags = {
    'Team': 'kubebois'
}
cluster_version = '1.14'

network_stack = infra.network.NetworkStack(
    scope=app,
    id=name + '-network',
    cidr_id=100,
    cluster_name=cluster_name,
    env=env,
    tags=tags
)
cluster_stack = infra.eks.EksStack(
    scope=app,
    id=name + '-eks',
    cluster_name=cluster_name,
    cluster_version=cluster_version,
    vpc=network_stack.vpc,
    env=env,
    tags=tags,
)
cluster_users_stack = infra.cluster_users.ClusterUsersStack(
    scope=app,
    id=name + '-users',
    clusters=[cluster_stack.cluster],
    env=env,
    tags=tags
)

app.synth()
