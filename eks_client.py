import base64
import boto3
import kubernetes
import tempfile
import subprocess
import json

def for_cluster(cluster: str) -> kubernetes.client.ApiClient:
    eks_client = boto3.client('eks')
    eks_details = eks_client.describe_cluster(name=cluster)['cluster']
    endpoint = eks_details['endpoint']
    ca_data = eks_details['certificateAuthority']['data']
    
    conf = kubernetes.client.Configuration()
    conf.host = endpoint
    conf.api_key['authorization'] = _get_token(cluster)
    conf.api_key_prefix['authorization'] = 'Bearer'
    conf.ssl_ca_cert = _save_eks_ca_cert(ca_data)
    
    return kubernetes.client.ApiClient(conf)

def _get_token(cluster: str) -> str:
    args = ('aws', 'eks', 'get-token', '--cluster-name', cluster)
    out = subprocess.run(args, capture_output=True, check=True)
    out_json = json.loads(out.stdout)
    return out_json['status']['token']

def _save_eks_ca_cert(ca_cert_b64: str) -> str:
    fp = tempfile.NamedTemporaryFile(delete=False)
    cert_bs = base64.urlsafe_b64decode(ca_cert_b64.encode('utf-8'))
    fp.write(cert_bs)
    fp.close()
    return fp.name
