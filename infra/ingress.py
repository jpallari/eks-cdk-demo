import typing

from aws_cdk import (
    core,
    aws_ec2,
    aws_elasticloadbalancing as aws_elb,
)

class IngressConstruct(core.Construct):
    def __init__(
        self,
        scope: core.Construct,
        id: str,
        vpc: aws_ec2.IVpc,
        instance_port: int,
        internet_facing: bool,
        subnets: typing.List[aws_ec2.ISubnet],
        targets: typing.List[aws_elb.ILoadBalancerTarget],
        ssl_certificate_id: typing.Optional[str],
        allow_connections_from: typing.Optional[typing.List[aws_ec2.IConnectable]]=None,
    ) -> None:
        super().__init__(scope, id)
        
        self.elb = aws_elb.LoadBalancer(
            scope=self,
            id='elb',
            vpc=vpc,
            internet_facing=internet_facing,
            subnet_selection=aws_ec2.SubnetSelection(subnets=subnets),
            targets=targets,
            health_check=aws_elb.HealthCheck(
                port=instance_port,
                path='/healthz',
                protocol=aws_elb.LoadBalancingProtocol.HTTP,
                healthy_threshold=2,
                interval=core.Duration.seconds(amount=10),
                timeout=core.Duration.seconds(amount=5),
                unhealthy_threshold=3,
            ),
        )
        self.elb.add_listener(
            external_port=80,
            external_protocol=aws_elb.LoadBalancingProtocol.HTTP,
            internal_port=instance_port,
            internal_protocol=aws_elb.LoadBalancingProtocol.HTTP,
            allow_connections_from=allow_connections_from,
        )
        if ssl_certificate_id:
            self.elb.add_listener(
                external_port=443,
                external_protocol=aws_elb.LoadBalancingProtocol.HTTPS,
                internal_port=instance_port,
                internal_protocol=aws_elb.LoadBalancingProtocol.HTTP,
                allow_connections_from=allow_connections_from,
                ssl_certificate_id=ssl_certificate_id,
            )

        # TODO: hosted zone
