from aws_cdk import (
    core,
    aws_ec2,
)

class NetworkStack(core.Stack):
    def __init__(
        self,
        scope: core.Construct,
        id: str,
        cidr_id: int,
        cluster_name: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, id, **kwargs)

        self.vpc = aws_ec2.Vpc(
            scope=self,
            id='eks',
            cidr='10.%d.0.0/16' % cidr_id,
            subnet_configuration=[
                aws_ec2.SubnetConfiguration(
                    name='public',
                    subnet_type=aws_ec2.SubnetType.PUBLIC,
                    cidr_mask=23,
                ),
                aws_ec2.SubnetConfiguration(
                    name='private',
                    subnet_type=aws_ec2.SubnetType.PRIVATE,
                    cidr_mask=18,
                ),
            ],
        )

        core.Tag.add(
            scope=self.vpc,
            key='kubernetes.io/cluster/%s' % cluster_name,
            value='shared',
        )

        for subnet in self.vpc.private_subnets:
            core.Tag.add(
                scope=subnet,
                key='kubernetes.io/role/internal-elb',
                value='1',
            )
            core.Tag.add(
                scope=subnet,
                key='kubernetes.io/cluster/%s' % cluster_name,
                value='shared',
            )

        for subnet in self.vpc.public_subnets:
            core.Tag.add(
                scope=subnet,
                key='kubernetes.io/role/elb',
                value='1',
            )
