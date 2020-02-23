import typing
import eks_user

from aws_cdk import (
    core,
    aws_eks,
    aws_iam,
)

class ClusterUsersStack(core.Stack):
    def __init__(
        self,
        scope: core.Construct,
        id: str,
        clusters: typing.List[aws_eks.ICluster],
        **kwargs,
    ) -> None:
        super().__init__(scope, id, **kwargs)

        principal = aws_iam.AccountRootPrincipal()

        self.admin = eks_user.eks_user(
            scope=self,
            id='eks-admin',
            role_name=id + '-admin',
            k8s_username='admin',
            k8s_groups=['system:masters'],
            clusters=clusters,
            principal=principal,
        )

        self.dev_team_x = eks_user.eks_user(
            scope=self,
            id='eks-dev-team-x',
            role_name=id + '-dev-team-x',
            k8s_username='dev-team-x',
            k8s_groups=['dev-team-x'],
            clusters=clusters,
            principal=principal,
        )

        self.dev_team_y = eks_user.eks_user(
            scope=self,
            id='eks-dev-team-y',
            role_name=id + '-dev-team-y',
            k8s_username='dev-team-y',
            k8s_groups=['dev-team-y'],
            clusters=clusters,
            principal=principal,
        )

        self.cluster_users = [self.admin, self.dev_team_x, self.dev_team_y]
