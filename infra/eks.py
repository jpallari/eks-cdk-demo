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
        self.cluster_version = cluster_version
        self.vpc = vpc

        # Control plane

        self.control_plane_sg = self._control_plane_sg(id='control-plane-sg')
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

        self.node_sg = self._create_node_sg(id='node-sg')
        self.default_asg = self._node_group(
            name='default',
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

    def _control_plane_sg(self, id: str) -> aws_ec2.ISecurityGroup:
        sg = aws_ec2.SecurityGroup(
            scope=self,
            id=id,
            vpc=self.vpc,
        )
        return sg

    def _create_node_sg(self, id: str) -> aws_ec2.ISecurityGroup:
        sg = aws_ec2.SecurityGroup(
            scope=self,
            id=id,
            vpc=self.vpc,
            allow_all_outbound=True,
        )
        _add_eks_owned_tag(sg, self.cluster)

        # Allow all within the worker nodes
        sg.add_ingress_rule(
            peer=sg,
            connection=aws_ec2.Port.all_traffic(),
        )

        # Allow ports 0-65535 from control plane to workers
        sg.add_ingress_rule(
            peer=self.control_plane_sg,
            connection=aws_ec2.Port.tcp_range(start_port=0, end_port=65535),
        )
        self.control_plane_sg.add_egress_rule(
            peer=sg,
            connection=aws_ec2.Port.tcp_range(start_port=0, end_port=65535),
        )

        # Allow port 443 from workers to control plane
        self.control_plane_sg.add_ingress_rule(
            peer=sg,
            connection=aws_ec2.Port.tcp(port=443),
        )

        return sg

    def _node_group(
        self,
        name: str,
        instance_type: aws_ec2.InstanceType,
        min_capacity: int,
        max_capacity: int,
        root_volume_size: int=20,
        kubelet_extra_args: typing.Optional[dict]=None,
        rolling_update_pause_time: typing.Optional[core.Duration]=None,
    ) -> aws_autoscaling.IAutoScalingGroup:
        role = eks_user.eks_node_role(
            scope=self,
            id=f'{name}-node-role',
            cluster=self.cluster,
        )
        user_data = self._node_userdata(
            _kubelet_args_to_str(name, labels={}, args=kubelet_extra_args)
        )
        subnets = aws_ec2.SubnetSelection(subnets=self.cluster.vpc.private_subnets)
        rolling_upgrade_config = aws_autoscaling.RollingUpdateConfiguration(
            max_batch_size=1,
            min_instances_in_service=1,
            pause_time=rolling_update_pause_time,
            suspend_processes=[
                aws_autoscaling.ScalingProcess.AZ_REBALANCE,
            ],
        )
        ami = aws_eks.EksOptimizedImage(
            kubernetes_version=self.cluster_version,
            node_type=aws_eks.NodeType.STANDARD,
        )
        block_device = aws_autoscaling.BlockDevice(
            device_name='/dev/xvda',
            volume=aws_autoscaling.BlockDeviceVolume.ebs(
                volume_size=root_volume_size,
                delete_on_termination=True
            ),
        )
        asg = aws_autoscaling.AutoScalingGroup(
            scope=self,
            id=f'{name}-node-asg',
            block_devices=[block_device],
            instance_type=instance_type,
            machine_image=ami,
            user_data=aws_ec2.UserData.custom(content=user_data),
            vpc=self.cluster.vpc,
            role=role,
            min_capacity=min_capacity,
            max_capacity=max_capacity,
            vpc_subnets=subnets,
            update_type=aws_autoscaling.UpdateType.ROLLING_UPDATE,
            allow_all_outbound=False,
            rolling_update_configuration=rolling_upgrade_config,
        )
        asg.add_security_group(self.node_sg)
        _add_eks_owned_tag(asg, self.cluster)
        return asg

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

def _kubelet_args_to_str(
    name: str,
    labels: dict,
    args: dict,
) -> str:
    _labels = {
        f'node-role.kubernetes.io/{name}': '',
        'node-role': name,
    }
    if labels:
        _labels.update(labels)

    _args = {
        'node-labels': _dict_to_labels_str(labels)
    }
    if args:
        _args.update(args)
    
    return _dict_to_cli_args_str(_args)

def _dict_to_labels_str(d: dict) -> str:
    return ','.join([
        '%s=%s' % (k, v)
        for k, v in d.items()
    ])

def _dict_to_cli_args_str(d: dict) -> str:
    return ' '.join([
        '--%s=%s' % (k, v)
        for k, v in d.items()
    ])

def _add_eks_owned_tag(
    scope: core.Construct,
    cluster: aws_eks.ICluster,
) -> None:
    core.Tag.add(
        scope=scope,
        key='kubernetes.io/cluster/%s' % cluster.cluster_name,
        value='owned',
        apply_to_launched_instances=True,
    )
