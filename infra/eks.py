import typing
import eks_worker
import ingress

from aws_cdk import (
    core,
    aws_ec2,
    aws_eks,
)

class EksStack(core.Stack):
    def __init__(
        self,
        scope: core.Construct,
        id: str,
        cluster_version: str,
        cluster_name: str,
        vpc: aws_ec2.IVpc,
        **kwargs,
    ) -> None:
        super().__init__(scope, id, **kwargs)

        # Control plane
        self.control_plane_sg = aws_ec2.SecurityGroup(
            scope=self,
            id='control-plane-sg',
            vpc=vpc,
            allow_all_outbound=False,
            description='EKS control plane SG for cluster %s' % cluster_name,
        )
        self.cluster = aws_eks.Cluster(
            scope=self,
            id='cluster',
            cluster_name=cluster_name,
            kubectl_enabled=False,
            default_capacity=0,
            vpc=vpc,
            version=cluster_version,
            security_group=self.control_plane_sg,
        )

        # Nodes
        self.default_worker = eks_worker.EksWorker(
            scope=self,
            id='default-nodes',
            name='default',
            stack_name=self.stack_name,
            region=self.region,
            cluster_version=cluster_version,
            cluster=self.cluster,
            control_plane_sg=self.control_plane_sg,
            instance_type=aws_ec2.InstanceType.of(
                instance_class=aws_ec2.InstanceClass.BURSTABLE3,
                instance_size=aws_ec2.InstanceSize.LARGE,
            ),
            min_capacity=1,
            max_capacity=5,
            rolling_update_pause_time=core.Duration.minutes(amount=1),
            kubelet_extra_args={
                'eviction-hard': 'memory.available<0.5Gi,nodefs.available<5%',
            }
        )

        # Ingress
        self.public_ingress = ingress.IngressConstruct(
            scope=self,
            id='public-ingress',
            vpc=vpc,
            instance_port=32080,
            internet_facing=True,
            subnets=vpc.public_subnets,
            targets=self.default_worker.asgs,
            ssl_certificate_id=None,
        )
        self.private_ingress = ingress.IngressConstruct(
            scope=self,
            id='private-ingress',
            vpc=vpc,
            instance_port=31080,
            internet_facing=False,
            subnets=vpc.private_subnets,
            targets=self.default_worker.asgs,
            allow_connections_from=[
                aws_ec2.Peer.ipv4('10.0.0.0/8'),
            ],
            ssl_certificate_id=None,
        )
