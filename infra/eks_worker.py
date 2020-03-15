import typing
import eks_user

from aws_cdk import (
    core,
    aws_autoscaling,
    aws_ec2,
    aws_eks,
)

class EksWorker(core.Construct):
    def __init__(
        self,
        scope: core.Construct,
        id: str,
        name: str,
        stack_name: str,
        region: str,
        cluster_version: str,
        cluster: aws_eks.ICluster,
        control_plane_sg: aws_ec2.ISecurityGroup,
        instance_type: aws_ec2.InstanceType,
        min_capacity: int,
        max_capacity: int,
        root_volume_size: int=20,
        kubelet_extra_args: typing.Optional[dict]=None,
        rolling_update_pause_time: typing.Optional[core.Duration]=None,
        autoscaling_enabled: bool=True,
    ) -> None:
        super().__init__(scope, id)

        self.sg = aws_ec2.SecurityGroup(
            scope=self,
            id='sg',
            vpc=cluster.vpc,
            allow_all_outbound=True,
            description='EKS node SG for cluster %s' % cluster.cluster_name,
        )
        _add_eks_owned_tag(self.sg, cluster)

        # Allow all within the worker nodes
        self.sg.add_ingress_rule(
            peer=self.sg,
            connection=aws_ec2.Port.all_traffic(),
        )

        # Allow ports 0-65535 from control plane to workers
        self.sg.add_ingress_rule(
            peer=control_plane_sg,
            connection=aws_ec2.Port.tcp_range(start_port=0, end_port=65535),
        )
        control_plane_sg.add_egress_rule(
            peer=self.sg,
            connection=aws_ec2.Port.tcp_range(start_port=0, end_port=65535),
        )

        # Allow port 443 from workers to control plane
        control_plane_sg.add_ingress_rule(
            peer=self.sg,
            connection=aws_ec2.Port.tcp(port=443),
        )

        self.role = eks_user.eks_node_role(
            scope=self,
            id='node-role',
            cluster=cluster,
        )
        rolling_upgrade_config = aws_autoscaling.RollingUpdateConfiguration(
            max_batch_size=1,
            min_instances_in_service=1,
            pause_time=rolling_update_pause_time,
            suspend_processes=[
                aws_autoscaling.ScalingProcess.AZ_REBALANCE,
            ],
        )
        ami = aws_eks.EksOptimizedImage(
            kubernetes_version=cluster_version,
            node_type=aws_eks.NodeType.STANDARD,
        )
        block_device = aws_autoscaling.BlockDevice(
            device_name='/dev/xvda',
            volume=aws_autoscaling.BlockDeviceVolume.ebs(
                volume_size=root_volume_size,
                delete_on_termination=True
            ),
        )
        
        # ASGs per availability zone to keep nodes balanced between zones
        self.asgs = []
        for index, subnet in enumerate(cluster.vpc.private_subnets):
            zone = subnet.availability_zone
            user_data = _node_userdata(
                cluster=cluster,
                stack_name=stack_name,
                region=region,
                kubelet_extra_args=_kubelet_args_to_str(
                    name=name,
                    labels={'aws-zone': zone},
                    args=kubelet_extra_args
                )
            )
            asg = aws_autoscaling.AutoScalingGroup(
                scope=self,
                id=f'asg-{index}',
                block_devices=[block_device],
                instance_type=instance_type,
                machine_image=ami,
                user_data=aws_ec2.UserData.custom(content=user_data),
                vpc=cluster.vpc,
                role=self.role,
                min_capacity=min_capacity,
                max_capacity=max_capacity,
                vpc_subnets=aws_ec2.SubnetSelection(subnets=[subnet]),
                update_type=aws_autoscaling.UpdateType.ROLLING_UPDATE,
                allow_all_outbound=False,
                rolling_update_configuration=rolling_upgrade_config,
            )
            asg.add_security_group(self.sg)
            _add_eks_owned_tag(asg, cluster)

            # Cluster auto-scaling config
            core.Tag.add(
                scope=asg,
                key='k8s.io/cluster-autoscaler/%s' % cluster.cluster_name,
                value='owned',
                apply_to_launched_instances=True,
            )
            core.Tag.add(
                scope=asg,
                key='k8s.io/cluster-autoscaler/enabled',
                value='true' if autoscaling_enabled else 'false',
                apply_to_launched_instances=True,
            )
            self.asgs.append(asg)

def _node_userdata(
    cluster: aws_eks.ICluster,
    stack_name: str,
    region: str,
    kubelet_extra_args: str,
) -> str:
        return f'''
#!/bin/bash
set -o xtrace
/etc/eks/bootstrap.sh \
    {cluster.cluster_name} \
    --kubelet-extra-args "{kubelet_extra_args}"
/opt/aws/bin/cfn-signal --exit-code $? \
        --stack {stack_name} \
        --resource NodeGroup  \
        --region {region}'''

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
        'node-labels': _dict_to_str(
            d=_labels,
            kv_pattern='%s=%s',
            separator=','
        ),
    }
    if args:
        _args.update(args)
    
    return _dict_to_str(
        d=_args,
        kv_pattern='--%s=%s',
        separator=' ',
    )

def _dict_to_str(d: dict, kv_pattern: str, separator: str) -> str:
    elements = [
        kv_pattern % (k, v)
        for k, v in d.items()
    ]
    
    # Sort the elements to keep the outcome idempotent.
    # If not sorted, the output will change due to dictionary not being sorted.
    # Technically, the output will be valid in any order,
    # but it can cause unnecessary changes to be rolled out.
    elements.sort()

    return separator.join(elements)

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
