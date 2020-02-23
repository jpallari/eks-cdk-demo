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

        node_security_group = aws_ec2.SecurityGroup(
            scope=self,
            id='eks-node-sg',
            vpc=cluster.vpc,
        )
        node_security_group.add_ingress_rule(
            peer=node_security_group,
            connection=aws_ec2.Port.all_traffic(),
        )
        node_security_group.add_ingress_rule(
            peer=cluster_sg,
            connection=aws_ec2.Port.tcp(port=443)
        )
        node_security_group.add_egress_rule(
            peer=cluster_sg,
            connection=aws_ec2.Port.tcp_range(start_port=1025, end_port=65535)
        )

        default_node_group_role = eks_user.eks_node_role(
            scope=self,
            id='eks-default-node-role',
            role_name=id + '-default-node-role',
            cluster=cluster,
        )

        default_node_group_asg = aws_autoscaling.AutoScalingGroup(
            scope=self,
            id='default-node-asg',
            block_devices=[
                aws_autoscaling.BlockDevice(
                    device_name='/dev/xvda',
                    volume=aws_autoscaling.BlockDeviceVolume.ebs(
                        volume_size=20,
                        delete_on_termination=True
                    ),
                )
            ],
            instance_type=aws_ec2.InstanceType.of(
                instance_class=aws_ec2.InstanceClass.BURSTABLE3,
                instance_size=aws_ec2.InstanceSize.LARGE,
            ),
            machine_image=aws_eks.EksOptimizedImage(
                kubernetes_version=cluster_version,
                node_type=aws_eks.NodeType.STANDARD,
            ),
            user_data=aws_ec2.UserData.custom(_node_userdata(
                cluster=cluster,
                stack_name=self.stack_name,
                region=self.region,
            )),
            vpc=cluster.vpc,
            role=default_node_group_role,
            max_capacity=5,
            min_capacity=1,
            vpc_subnets=aws_ec2.SubnetSelection(subnets=cluster.vpc.private_subnets),
            update_type=aws_autoscaling.UpdateType.ROLLING_UPDATE,
            rolling_update_configuration=aws_autoscaling.RollingUpdateConfiguration(
                max_batch_size=1,
                min_instances_in_service=1,
                pause_time=core.Duration.minutes(amount=5),
            ),
        )

        core.Tag.add(
            scope=default_node_group_asg,
            key='kubernetes.io/cluster/%s' % cluster.cluster_name,
            value='owned',
            apply_to_launched_instances=True,
        )
        

def _node_userdata(
    cluster: aws_eks.ICluster,
    stack_name: str,
    region: str,
) -> str:
    # TODO: bootstrap arguments
    return f'''
#!/bin/bash
set -o xtrace
/etc/eks/bootstrap.sh {cluster.cluster_name}
/opt/aws/bin/cfn-signal --exit-code $? \
        --stack {stack_name} \
        --resource NodeGroup  \
        --region {region}'''
