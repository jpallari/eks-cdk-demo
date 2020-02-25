import typing
import eks_user

from aws_cdk import (
    core,
    aws_autoscaling,
    aws_ec2,
    aws_eks,
    aws_iam,
    aws_ssm,
)

class EksMasterStack(core.Stack):
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

        self.cluster_sg = aws_ec2.SecurityGroup(
            scope=self,
            id='eks-control-plane-sg',
            vpc=vpc,
            allow_all_outbound=True,
        )

        self.cluster_sg.add_ingress_rule(
            peer=self.cluster_sg,
            connection=aws_ec2.Port.all_traffic(),
        )

        self.cluster = aws_eks.Cluster(
            scope=self,
            id='eks-cluster',
            cluster_name=cluster_name,
            kubectl_enabled=False,
            default_capacity=0,
            vpc=vpc,
            version=cluster_version,
            security_group=self.cluster_sg,
        )


class EksNodeGroupStack(core.Stack):
    def __init__(
        self,
        scope: core.Construct,
        id: str,
        cluster: aws_eks.ICluster,
        cluster_version: str,
        cluster_sg: aws_ec2.ISecurityGroup,
        **kwargs,
    ) -> None:
        super().__init__(scope, id, **kwargs)
        self.cluster = cluster
        self.cluster_version = cluster_version
        self.cluster_sg = cluster_sg

        node_sg = self._create_node_sg()
        self.default_asg = self._node_group(
            name='default',
            instance_type=aws_ec2.InstanceType.of(
                instance_class=aws_ec2.InstanceClass.BURSTABLE3,
                instance_size=aws_ec2.InstanceSize.LARGE,
            ),
            node_sg=node_sg,
            min_capacity=1,
            max_capacity=5,
            rolling_update_pause_time=core.Duration.minutes(amount=1),
        )

    def _node_group(
        self,
        name: str,
        instance_type: aws_ec2.InstanceType,
        node_sg: aws_ec2.ISecurityGroup,
        min_capacity: int,
        max_capacity: int,
        root_volume_size: int=20,
        kubelet_extra_args: typing.Optional[dict]=None,
        rolling_update_pause_time: typing.Optional[core.Duration]=None,
    ) -> aws_autoscaling.IAutoScalingGroup:
        role = eks_user.eks_node_role(
            scope=self,
            id=f'eks-{name}-node-role',
            cluster=self.cluster,
        )

        asg = aws_autoscaling.AutoScalingGroup(
            scope=self,
            id=f'{name}-node-asg',
            block_devices=[
                aws_autoscaling.BlockDevice(
                    device_name='/dev/xvda',
                    volume=aws_autoscaling.BlockDeviceVolume.ebs(
                        volume_size=root_volume_size,
                        delete_on_termination=True
                    ),
                )
            ],
            instance_type=instance_type,
            machine_image=aws_eks.EksOptimizedImage(
                kubernetes_version=self.cluster_version,
                node_type=aws_eks.NodeType.STANDARD,
            ),
            user_data=aws_ec2.UserData.custom(
                self._node_userdata(_kubelet_args_to_str(name, kubelet_extra_args))
            ),
            vpc=self.cluster.vpc,
            role=role,
            min_capacity=min_capacity,
            max_capacity=max_capacity,
            vpc_subnets=aws_ec2.SubnetSelection(subnets=self.cluster.vpc.private_subnets),
            update_type=aws_autoscaling.UpdateType.ROLLING_UPDATE,
            allow_all_outbound=False,
            rolling_update_configuration=aws_autoscaling.RollingUpdateConfiguration(
                max_batch_size=1,
                min_instances_in_service=1,
                pause_time=rolling_update_pause_time,
                suspend_processes=[
                    aws_autoscaling.ScalingProcess.AZ_REBALANCE,
                ],
            ),
        )
        asg.add_security_group(node_sg)

        core.Tag.add(
            scope=asg,
            key='kubernetes.io/cluster/%s' % self.cluster.cluster_name,
            value='owned',
            apply_to_launched_instances=True,
        )

        return asg

    def _create_node_sg(self) -> aws_ec2.ISecurityGroup:
        node_sg = aws_ec2.SecurityGroup(
            scope=self,
            id='eks-node-sg',
            vpc=self.cluster.vpc,
        )
        node_sg.add_ingress_rule(
            peer=node_sg,
            connection=aws_ec2.Port.all_traffic(),
        )
        node_sg.add_ingress_rule(
            peer=self.cluster_sg,
            connection=aws_ec2.Port.tcp(port=443)
        )
        node_sg.add_egress_rule(
            peer=self.cluster_sg,
            connection=aws_ec2.Port.tcp_range(start_port=1025, end_port=65535)
        )
        return node_sg

    def _node_userdata(
        self,
        kubelet_extra_args: str,
    ) -> str:
        return f'''
#!/bin/bash
set -o xtrace
/etc/eks/bootstrap.sh \
    {self.cluster.cluster_name} \
    --kubelet-extra-args "{kubelet_extra_args}"
/opt/aws/bin/cfn-signal --exit-code $? \
        --stack {self.stack_name} \
        --resource NodeGroup  \
        --region {self.region}'''

def _kubelet_args_to_str(name: str, args: typing.Optional[dict]) -> str:
    _args = {}
    _args.update({
        'eviction-hard': 'memory.available<0.5Gi,nodefs.available<5%',
        'node-labels': f'node-role.kubernetes.io/{name},node-role={name}',
    })
    if args:
        _args.update(args)
    
    return ' '.join([
        '--%s=%s' % (k, v)
        for k, v in _args.items()
    ])
