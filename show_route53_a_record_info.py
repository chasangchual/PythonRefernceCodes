#!/apollo/sbin/envroot "$ENVROOT/bin/python2.7"

import boto3
import argparse
import time
import pprint
from odin_client import AWSCredentialsProvider, TimedRefresher

ALPHA_STAGE = 'alpha'
BETA_STAGE = 'beta'
GAMMA_STAGE = 'gamma'
ONEBOX_STAGE = 'onebox'
PROD_STAGE = 'prod'

OLD_VPC = "old"
NEW_VPC = "new"

PPRINT_INDENT = 2
pp = pprint.PrettyPrinter(indent=PPRINT_INDENT)

MAT_SET_MAP = {
    ALPHA_STAGE: 'com.amazon.access.Tachyon-Sip-Registrar-Alpha-TachyonKamailioAWS-1',
    BETA_STAGE: 'com.amazon.access.Tachyon-Sip-Registrar-Beta-TachyonKamailioAWS-1',
    GAMMA_STAGE: 'com.amazon.access.Tachyon-Sip-Registrar-Gamma-TachyonKamailioAWS-1',
    PROD_STAGE: 'com.amazon.access.Tachyon-Sip-Registrar-Prod-TachyonKamailioAWS-1'
}

class AWSClient:
    def __init__(self, mat_set, region):
        refresher = TimedRefresher(90)
        credentials_provider = AWSCredentialsProvider(mat_set, refresher)
        aws_access_key_id, aws_secret_access_key = credentials_provider.aws_access_key_pair
        self.session = boto3.session.Session(region_name=region,
                                             aws_access_key_id=aws_access_key_id,
                                             aws_secret_access_key=aws_secret_access_key)

    def exit_on_boto_error(self, response):
        if 'Unsuccessful' in response and len(response['Unsuccessful']) > 0:
            pp.pprint(response)
            raise('Something is not right, see trace')

    def fail_if_not_single_resource(self, response, key):
        if key not in response or len(response[key]) != 1:
            pp.pprint(response)
            raise("Expectation for single resource not met")

    def get_hosted_zone_id(self, hosted_zone_name):
        response = self.session.client('route53').list_hosted_zones()
        self.exit_on_boto_error(response)
        for hosted_zone in response['HostedZones']:
            if hosted_zone['Name'] == hosted_zone_name:
                print("------------ hosted zone info ------------")
                pp.pprint(hosted_zone)
                return hosted_zone['Id']

    def get_hosted_zone_a_record(self, hosted_zone_id):
        response = self.session.client('route53').list_resource_record_sets(HostedZoneId=hosted_zone_id)
        self.exit_on_boto_error(response)

        arecords = []
        for record_set in response['ResourceRecordSets']:
            if record_set['Type'] == 'A':
                arecords.append(record_set)

        pp.pprint(arecords)
        return arecords

    def update_hosted_zone_a_record(self, hosted_zone_id, change_batch):
        self.session.client('route53').change_resource_record_sets(HostedZoneId=hosted_zone_id,
                                                                        ChangeBatch=change_batch)

    def get_elbs(self):
        elbs = []
        lbs = self.session.client('elb').describe_load_balancers(PageSize=256)
        # pp.pprint(lbs)

        for lb in lbs["LoadBalancerDescriptions"]:
            elb = {}
            elb["type"] = "network"
            elb["LoadBalancerName"] = lb["LoadBalancerName"]
            elb['AvailabilityZones'] = lb["AvailabilityZones"]
            elb["Subnets"] = lb["Subnets"]
            elb["VPCId"] = lb["VPCId"]
            if 'DNSName' in lb:
                elb["DNSName"] = lb["DNSName"]
            elif 'CanonicalHostedZoneName' in lb:
                    elb["DNSName"] = lb["CanonicalHostedZoneName"]
            elb["CanonicalHostedZoneNameID"] = lb["CanonicalHostedZoneNameID"]
            elb["CreatedTime"] = lb["CreatedTime"]
            elb["Scheme"] = lb["Scheme"]
            elb["SecurityGroups"] = lb["SecurityGroups"]
            elbs.append(elb)
        #pp.pprint(elbs)
        return elbs

    def get_elbsv2(self):
        elbs = []
        lbs = self.session.client('elbv2').describe_load_balancers(PageSize=256)
        # pp.pprint(lbs)
        for lb in lbs["LoadBalancers"]:
            elb = {}
            elb["type"] = "application"
            elb["LoadBalancerName"] = lb["LoadBalancerName"]
            elb["AvailabilityZones"] = lb["AvailabilityZones"]
            elb["Subnets"] = []
            elb["VPCId"] = lb["VpcId"]
            if 'CanonicalHostedZoneName' in lb:
                elb["DNSName"] = lb["CanonicalHostedZoneName"]
            elif 'DNSName' in lb:
                    elb["DNSName"] = lb["DNSName"]
            elb["CanonicalHostedZoneNameID"] = lb["CanonicalHostedZoneId"]
            elb["CreatedTime"] = lb["CreatedTime"]
            elb["Scheme"] = lb["Scheme"]
            if 'SecurityGroups' in lb:
                elb["SecurityGroups"] = lb["SecurityGroups"]
            else:
                elb["SecurityGroups"] = []
            elbs.append(elb)
        return elbs


def show_route53_info(client, hosted_zone_name):
    hosted_zone_id = client.get_hosted_zone_id(hosted_zone_name)
    if hosted_zone_id is not None:
        arocrds = client.get_hosted_zone_a_record(hosted_zone_id)
        # print("------------ A Records ------------")
        # pp.pprint(arocrds)
        # print("------------ ELBs ------------")
        elbs = client.get_elbs()
        elbsv2 = client.get_elbsv2()
        # elbs.append(client.get_elbsv2())
        # pp.pprint(elbs)
        show_route53_a_record_info(1, arocrds, elbs, elbsv2)


def show_route53_a_record_info(level, arecords, elbs, elbsv2):
    for arecord in arecords:
        arecord_dns = arecord["AliasTarget"]["DNSName"]
        found_arocrds = find_arecord_with_dns(arecords, arecord_dns)
        if level == 1:
            print("======================================================================================")
        print("[" + str(level) + "] ------------ A Records ------------")
        pp.pprint(arecord)

        if not found_arocrds:
            found_elb = find_elb_with_dns(elbs, arecord_dns)
            if found_elb is None:
                found_elbv2 = find_elb_with_dns(elbsv2, arecord_dns)
                if found_elbv2 is not None:
                    print("[" + str(level) + "] ------------ ELB v2 ------------")
                    pp.pprint(found_elbv2)
            else:
                print("[" + str(level) + "] ------------ ELB ------------")
                pp.pprint(found_elb)
        else:
            show_route53_a_record_info(level +1, found_arocrds, elbs, elbsv2)


def find_arecord_with_dns(arecords, dns_name):
    found_arecords = []

    for arecord in arecords:
        if arecord["Name"].upper() == dns_name.upper():
            found_arecords.append(arecord)

    return found_arecords


def find_elb_with_dns(elbs, dns_name):
    dns_name = dns_name[:-1] if dns_name[-1] == '.' else dns_name
    for elb in elbs:
        if "DNSName" in elb:
            dns_name = dns_name.upper()[10:] if dns_name.upper().find("DUALSTACK.") != -1 else dns_name.upper()
            if elb["DNSName"].upper() == dns_name.upper():
                # print("------------ found ELB ------------")
                # pp.pprint(elb["DNSName"].upper() + " == " + dns_name)
                # pp.pprint(elb)
                return elb
    return None

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Changes DNS weighting to/from new EP VPC ELB')
    parser.add_argument('-s', '--stage', help='The stage to look into', required=True,
                        choices=[ALPHA_STAGE, BETA_STAGE, GAMMA_STAGE, PROD_STAGE])
    parser.add_argument('-r', '--region', help='The region of AWS account', default='us-east-1')
    parser.add_argument('-hz', '--hosted_zone', help='Hosted zone name. expecting it ends with \'.\'')

    args = parser.parse_args()
    pp.pprint(args)

    client = AWSClient(MAT_SET_MAP[args.stage], args.region)

    show_route53_info(client, args.hosted_zone)
    print("Done.")
