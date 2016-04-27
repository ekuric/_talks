#!/usr/bin/env python 

# program to create Openshift pods using nfs/ebs/ceph or gluster as persistent storage for pods
# License GPL2/3

__author__ = "elko"

import argparse
import boto3
import subprocess
import json
import botocore   
import time 
import rados 
import rbd
import logging

class CreatePod():

    def __init__(self,formatter,ebs_logger,ebsh,ceph_logger,cephh,gluster_logger,glusterh,pod_logger,podh):

        print ("Program to create EBS volume and pv/pvc based on EBS")

    def ec2_volume(self,ebsvolumesize,ebstype,ebsregion,ebstagprefix,num):
        """
        create EBS volume at EC2 side. In order this to work, Openshift machine must be configured with 
        proper EC2 keys and authentication 
        """

        self.ebsvolumesize = ebsvolumesize
        self.ebstype = ebstype  
        self.ebsregion = ebsregion 
        self.ebstagprefix = ebstagprefix
        self.num = num 

        global tags
        global ebsvolumeid
        ec2 = boto3.resource("ec2")
        while True:
            try:
                ebsvolume = ec2.create_volume(VolumeType=ebstype,AvailabilityZone=ebsregion,Size=ebsvolumesize)
                ebsvolumeid = ebsvolume.id
            except botocore.exceptions.ClientError as err:
                ebs_logger.info('%s %s', "Exception happened", err.response['Error']['Code'])
                continue 

            # try to tag volume 
            try: 
                tags = ec2.create_tags(DryRun=False, Resources=[ebsvolume.id],Tags=[{'Key': ebstagprefix + ebsvolume.id,'Value': ebstagprefix},])
            except botocore.exceptions.ClientError as err:
                ebs_logger.info('%s', "Exception happeded, but we have to tag every volume - sleeping 5 sec")
                time.sleep(5)
                continue 
                try:
                    tags = ec2.create_tags(DryRun=False, Resources=[ebsvolume.id],Tags=[{'Key': ebstagprefix + ebsvolume.id,'Value': ebstagprefix},])
                except:
                    ebs_logger.info('%s %s %s', "Volume", ebsvolumeid, "is not tagged")
            else:
                ebs_logger.info('%s %s', "Volume tagged", ebsvolumeid)
            break 

    def ceph_volume(self,cephpool,cephimagename,cephimagesize,num):    


        self.cephpool = cephpool 
        self.cephimagename = cephimagename
        self.cephimagesize = cephimagesize
        self.num = num 
        """
        create ceph cluster handle
        defaults : user=admin, conffile=/etc/ceph/ceph.conf
        """
        try:
            cluster = rados.Rados(conffile="/etc/ceph/ceph.conf")
            cluster.connect()
            ceph_logger.info('%s', "connected to ceph cluster") 
        except Exception as e:
            ceph_logger.info('%s %s', "Not possible to connect to ceph cluster", e) 
            raise
        print ("Connected")
        ceph_logger.info('%s', "Connection to CEPH cluster was sucessfull")

        """
        Create desired number of images - these will be used by pods
        """  
        iocntx = cluster.open_ioctx(cephpool)
        rbd_ins = rbd.RBD()
        try:
        	rbd_ins.create(iocntx, str(cephimagename) + str(num) , int(cephimagesize) * 1024**3 )
        	ceph_logger.info('%s %s %s %s %s' , "ceph image", str(cephimagename) + str(num), "with size of ", int(cephimagesize), "GB was created")
        except Exception:
        	ceph_logger.info('%s', "Error happened ... check log")
  
    def pebsvolume(self,pvfile,pvsize,num):
        """
        create persistant volume on top of ec2 EBS device
        """ 

        self.pvfile = pvfile
        self.pvsize = pvsize
        self.num = num 
        
        with open(pvfile, "r") as pvhandler:
            pvjson = json.load(pvhandler)
        
        pvvanila = { "metadata": {"name": "p" + ebsvolumeid },
                     'spec': {'capacity': {'storage': str(pvsize) + "Gi" },
                              'persistentVolumeReclaimPolicy': 'Recycle', 'accessModes': ['ReadWriteOnce'],
                              'awsElasticBlockStore': {'volumeID': ebsvolumeid , 'fsType': fstype }}}
        pvjson.update(pvvanila)
        json.dump(pvjson, open("pvfile.json", "w+"),sort_keys=True, indent=4, separators=(',', ': '))
        subprocess.call(["oc", "create", "-f", "pvfile.json"])


    def pcephvolume(self,pvfile,pvsize,cephsecret,cephmonitors,num):
        """
        create persistant volume on top of CEPH RBD device 
        """ 
        
        self.pvfile = pvfile 
        self.pvsize = pvsize
        self.num = num
        self.cephsecret = cephsecret 
        self.cephmonitors = cephmonitors
  

        with open(pvfile, "r") as pvhand:
            pvjson = json.load(pvhand)

        pvvanila = { "metadata": {"name": "p" + pvpvc + str(num) },
                    'spec': {'capacity': {'storage': str(pvsize) + "Gi" },
                    'accessModes': ["ReadWriteOnce"],
                    'rbd':{"monitors":[cephmonitors], 'pool': cephpool, "image": cephimagename + str(num), "user": "admin","fstype": fstype,
                    "secretRef": {"name": cephsecret }}}}
        pvjson.update(pvvanila)
        json.dump(pvjson, open("pvfile.json", "w+"),sort_keys=True, indent=4, separators=(',', ': '))
        subprocess.call(["oc", "create", "-f", "pvfile.json"])
  
    def pglustervolume(self, pvfile, pvsize, glustervolume, glusterfsep, num):
        """ 
        create persistant volume on top of gluster volume
        expected to have in advance information as 
        glustervolume, glusterip, glusterfsep 
        """ 
  
        self.glustervolume = glustervolume
        self.num = num
        self.pvfile = pvfile
        self.pvsize = pvsize 
        self.glusterfsep = glusterfsep 

        with open(pvfile, "r") as pvhgluster:
            pvjson = json.load(pvhgluster)

        pvvanila = { "metadata": {"name": "p" + pvpvc + str(num)},
                    'spec': {'capacity': {'storage': str(pvsize) + "Gi" },
                    'accessModes': ["ReadWriteOnce"],
                    'glusterfs':{"endpoints":glusterfsep, 'path': glustervolume}}}

        pvjson.update(pvvanila)
        json.dump(pvjson,open("pvfile.json", "w+"), sort_keys=True, indent=4, separators=(',', ': '))
        subprocess.call(["oc", "create", "-f", "pvfile.json"])

    def pnfsvolume(self,pvfile,pvsize,nfsip, nfsshare,num):
        """
        create persistant volume on top of NFS share
        expected to know information related to nfs share as 
        nfsshare - share to use, and nfsip - ip address of nfs share 
        """ 
        self.pvfile = pvfile 
        self.pvcfile = pvcfile 
        self.nfsip = nfsip
        self.nfsshare = nfsshare 
        self.num = num 

        with open(pvfile, "r") as pvhnfs:
        	pvjson = json.load(pvhnfs)

        pvvanila = { "metadata": {"name": "p" + pvpvc + str(num) },
                    'spec': {'capacity': {'storage': str(pvsize) + "Gi" },
                    'accessModes': ["ReadWriteOnce"],
                    'nfs':{"server": nfsip,'path': nfsshare}}}
        pvjson.update(pvvanila)
      	json.dump(pvjson, open("pvfile.json", "w+"), sort_keys=True, indent=4, separators=(',', ': '))
      	subprocess.call(["oc", "create", "-f", "pvfile.json"])


    # create persistent volume claim 
    def pclaim(self,pvcfile,pvcsize,num):
        """
        create persistant volume claim 
        This is common for all storge types 
        """ 

        self.pvcfile = pvcfile
        self.pvcsize= pvcsize
        self.num = num 

        with open(pvcfile,"r") as pvchand:
            pvcjson = json.load(pvchand)
        
        pvcvanila = {'metadata': {"name":"pvc" + pvpvc + str(num) },
                          'spec': {'accessModes': ['ReadWriteOnce'], 'resources': {'requests': {'storage': str(pvcsize) + "Gi" }}}}
        pvcjson.update(pvcvanila)
        json.dump(pvcjson, open("pvcfile.json", "w+"),sort_keys=True, indent=4, separators=(',', ': '))
        subprocess.call(["oc", "create", "-f", "pvcfile.json" ])

    # create pod 
    def ppod(self,image,podfile,mountpoint,num):
        """ 
        createp pod and use persistnt volumea and persistant volume claim created in above steps 
        """ 
        self.image = image 
        self.podfile = podfile
        self.mountpoint = mountpoint 
        self.num = num 

        with open(self.podfile,"r") as podhandler:
            podjson = json.load(podhandler)
        
        podvanila = {'metadata': {'name': "pod" + pvpvc + str(num)},
                         'spec': {'containers': [{'image': image,
                                                  'imagePullPolicy': 'IfNotPresent',
                                                  'name': "pod" + str(num),
                                                  'volumeMounts': [{'name': 'p' + pvpvc + str(num),
                                                  'mountPath': mountpoint }]}],
                                                  'volumes': [{'persistentVolumeClaim': {'claimName': "pvc" + pvpvc + str(num) }, 'name': "p" + pvpvc + str(num) }]}}
        podjson.update(podvanila)
        json.dump(podjson,  open("podfile.json", "w+"),sort_keys=True, indent=4, separators=(',', ': '))
        subprocess.call(["oc", "create", "-f", "podfile.json"])

if __name__ == "__main__":

    parser = argparse.ArgumentParser(description="Script to create OSE pods and attach one EBS volume per pod as persistent storage")

    # general parameters 
    parser.add_argument("--mountpoint", help="mount point inside pod", default="/mnt/persistentvolume")
    parser.add_argument("--image", help="docker image to use", default="fedora")
    parser.add_argument("--pvfile", help="persistent volume definition json file -- required parameter")
    parser.add_argument("--pvcfile", help="persistent volume claim definition json file - required parameter")
    parser.add_argument("--podfile", help="pod definition json file - required parameter")
    parser.add_argument("--pvsize", help="persistent volume size", default=1, type=int)
    parser.add_argument("--pvcsize", help="persistent volume claim size", default=1, type=int)
    parser.add_argument("--num", help="how many pods to create", default=1, type=int)
    parser.add_argument("--storage", help="what kind of storage to use, supported : nfs,gluster, ceph , ebs") 

    parser.add_argument("--ebsvolumesize", help="size of EBS volume - in GB", default=1, type=int)
    parser.add_argument("--ebstype", help="EBS volume type, default is gp2", default="gp2")
    parser.add_argument("--ebsregion", help="Amazon region where to connect and create EBS devices", default="us-west-2b")
    parser.add_argument("--ebstagprefix", help="EBS tag prefix", default="openshift-testing")

    # ceph 
    parser.add_argument("--cephpool", help="which ceph pool to use")
    parser.add_argument("--cephsecret", help="which cephsecret to use")
    parser.add_argument("--cephmonitors", help="comma separated list of ceph monitros, eg xx.xx.xx.xx:6789,yy.yy.yy.yy:6789")
    parser.add_argument("--cephimagename",help="prefix for ceph volumes")
    parser.add_argument("--cephimagesize", help="size of ceph rbd devices in GB") 
    parser.add_argument("--pvpvc", help="pv and pvc prefix ... for easier differentation")
    parser.add_argument("--fstype", help="file system to use")

    # gluster 
    parser.add_argument("--glustervolume", help="which gluster volume to use")
    parser.add_argument("--glusterfsep", help="glusterfsep - glusterfs end point")

    # nfs
    parser.add_argument("--nfsip", help="ip of nfs server")
    parser.add_argument("--nfsshare", help="the name of nfs share")


    # logger 
    logging.basicConfig(filename='create_pod.log', level=logging.INFO, format='%(message)s')
    formatter = logging.Formatter('%(message)s')

    # EBS logger 
    ebs_logger = logging.getLogger('ebslogger')
    ebsh = logging.FileHandler('ebscreate.log')
    ebsh.setFormatter(formatter)
    ebs_logger.addHandler(ebsh)

    # ceph logger 
    ceph_logger = logging.getLogger('cephlogger')
    cephh = logging.FileHandler('cephcreate.log')
    cephh.setFormatter(formatter)
    ceph_logger.addHandler(cephh)

    # gluster logger 
    gluster_logger = logging.getLogger('glusterlogger')
    glusterh = logging.FileHandler('glustercreate.log')
    glusterh.setFormatter(formatter)
    gluster_logger.addHandler(glusterh)
    
    # pod logger 
    pod_logger = logging.getLogger('podlogger')
    podh = logging.FileHandler('podcreate.log')
    podh.setFormatter(formatter)
    pod_logger.addHandler(podh)



    
    # parse arguments
    
    args = parser.parse_args()
    storage = args.storage 
    ebsvolumesize = args.ebsvolumesize
    ebstype = args.ebstype
    ebsregion = args.ebsregion
    ebstagprefix = args.ebstagprefix
    cephpool = args.cephpool
    cephsecret = args.cephsecret
    cephmonitors = args.cephmonitors

    mountpoint = args.mountpoint
    pvfile = args.pvfile
    pvcfile = args.pvcfile
    podfile = args.podfile
    pvsize = args.pvsize 
    pvcsize = args.pvcsize 
    num = args.num
    cephimagename = args.cephimagename
    cephimagesize = args.cephimagesize 
    pvpvc = args.pvpvc 
    image = args.image
    fstype = args.fstype 
    glustervolume = args.glustervolume
    glusterfsep = args.glusterfsep 
    nfsip = args.nfsip
    nfsshare = args.nfsshare




    create_pod = CreatePod(formatter,ebs_logger,ebsh,ceph_logger,cephh,gluster_logger,glusterh,pod_logger,podh)

    for num in range(0,int(num)):

        if storage == "ebs":
            create_pod.ec2_volume(ebsvolumesize,ebstype,ebsregion,ebstagprefix,num)
            create_pod.pebsvolume(pvfile,pvsize,num)
            create_pod.pclaim(pvcfile,pvcsize,num)
            create_pod.ppod(image,podfile,mountpoint,num)
                
        elif storage == "ceph":
            create_pod.ceph_volume(cephpool,cephimagename,cephimagesize,num)
            create_pod.pcephvolume(pvfile, pvsize,cephsecret,cephmonitors, num)
            create_pod.pclaim(pvcfile,pvcsize,num)
            create_pod.ppod(image,podfile,mountpoint,num)

        elif storage == "gluster":
        	create_pod.pglustervolume(pvfile, pvsize, glustervolume, glusterfsep, num)
        	create_pod.pclaim(pvcfile,pvcsize,num)
        	create_pod.ppod(image,podfile,mountpoint,num)
        elif storage == "nfs":
        	create_pod.pnfsvolume(pvfile,pvsize,nfsip, nfsshare,num)
        	create_pod.pclaim(pvcfile,pvcsize,num)
        	create_pod.ppod(image,podfile,mountpoint,num)
    

