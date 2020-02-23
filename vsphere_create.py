
"""
* Auhtor:		Dennis Tyresson
* Date:			2020-02-23
* Course:		IT524G Virtualization
* Description:	Python script for interacting with VMware vSphere to create vSwitch
*			 	or guest VM. The script takes several arguments, which can be displayed
*				by running the script with "-h", e.g. "python esxi-mgmt.py -h". The
*				script works with Python 3.6 or higher.
"""

import sys
import time
import argparse
import configparser
from pyVim import connect
from pyVmomi import vim, vmodl
from pyVim.task import WaitForTask

def get_args():
	'''Function to retrieve arguments passed to script'''
	parser = argparse.ArgumentParser(prog='esxi-mgmt.py',
	                                 description='''Administer new vSwitch or Virtual Machine for ESXi.
User must provide an action to perform; create switch 
or VM. A name for the unit to create is required.''',
	                                 formatter_class=argparse.RawTextHelpFormatter)

	parser.add_argument('--switch', 
						help="Create a switch",
						action='store_true')
	parser.add_argument('--vm', 
						help="Create a Virtual Machine",
						action='store_true')
	parser.add_argument('-n', '--name', 
						help="Name for device",
						action='store',
						required=True)
	parser.add_argument('-p', '--port-group', 
						help="Portgroup to attach to switch or VM",
						action='store')
	parser.add_argument('-t', '--template', 
						help="Name of template to use for deployment", 
						action='store')
	parser.add_argument('-v', '--vlan', 
						help="VLAN to attach to switch", 
						action='store')
	parser.add_argument('-m', '--mtu', 
						help="Specify MTU for new vSwitch 	(empty default to 1500)", 
						action="store", 
						type=int)
	parser.add_argument('-c', '--cpu', 
						help="Number of CPUs for VM", 
						action='store',
						type=int)
	parser.add_argument('-r', '--ram', 
						help="Amount of RAM in MB for VM", 
						action='store',
						type=int)
	parser.add_argument('-d', '--disk', 
						help="Size in GB of disk for VM", 
						action='store',
						type=int)

	# Dictionary with arguments to return
	args = {}
	result = parser.parse_args()

	# Only one action can be provided at a time
	if result.switch and result.vm:
		raise Exception('Can not create VM and switch at the same time.')

	# Required for all options
	args['name'] = result.name

	# Parse result for creating switch
	if result.switch:

		# Check for valid input
		if not result.vlan:
			raise Exception("No VLAN id provided.")
		if not result.port_group:
			raise Exception("No portgroup provided.")
		if result.mtu:
			if 0 < result.mtu < 9001:
				args['mtu'] = result.mtu
			elif not 0 < result.mtu < 9001:
				raise Exception('MTU must be a value between 1 and 9000.')
		else:
			args['mtu'] = 1500

		# Save arguments to dictionary
		args['action'] = 'switch'
		args['vlan'] = result.vlan
		args['port_group'] = result.port_group

	# Parse result for creating VM
	elif result.vm:

		# If user request deployment from template
		# no further check for hardware options required
		args['action'] = 'vm'
		if result.template:
			args['template'] = result.template
			return args

		# Check that hardware options are provided
		if not result.port_group:
			raise Exception("No portgroup provided.")
		if not result.cpu:
			raise Exception("No CPU option provided for VM")
		if not result.ram:
			raise Exception("No RAM option provided for VM")
		if not result.disk:
			raise Exception("No Disk option provided for VM")

		# Save arguments to dictionary
		args['cpu'] = result.cpu
		args['ram'] = result.ram
		args['disk'] = result.disk
		args['port_group'] = result.port_group
	else:
		raise Exception("No action specified!")
	return args

def get_conn_args():
	'''Get host info from config file'''
	config = configparser.ConfigParser()
	config.read('vsphere.conf')
	args['address'] = config['host']['ip address']
	args['username'] = config['host']['username']
	args['password'] = config['host']['password']
	return args

class ServerConnection():
	'''Server class from which connection to server takes place'''
	def __init__(self, args):
		try:
			self._connection = connect.ConnectNoSSL(args['address'], 443, args['username'], args['password'])
		except Exception as e:
			return f'Could not connect to server: {e}'
		self._content = self.connection.RetrieveContent()

	@property
	def connection(self):
		return self._connection

	@property
	def content(self):
		return self._content

	def disconnect(self):
		try:
			connect.Disconnect(self.connection)
		except Exception as e:
			return f'Could not close connection: {e}'

	def get_obj(self, vimtype, name=None):
		'''Function to get objects from vSphere'''
		obj = None
		try:
			container = self.content.viewManager.CreateContainerView(self.content.rootFolder, vimtype, True)

			# Search for name if provided, otherwise return list
			if name:
				for item in container.view:
					if item.name == name:
						obj = item
				container.Destroy()
				return obj
			obj_list = [item for item in container.view]
			container.Destroy()
			return obj_list
		except Exception as e:
			return f'Something went wrong: {e}'

	def check_hardware(self, hosts, args):
		'''Function that evaluate user input against available hardware resources'''
		datastore = self.content.rootFolder.childEntity[0].datastore
		for store in datastore:
			if store.name == "NFSstore":
				free_disk = (round(int(store.summary.freeSpace)/1024/1024/1024))
		saved_cpu = 0
		saved_memory = 0

		# Find host with most available resources
		for host in hosts:
			cpu = int(host.hardware.cpuInfo.numCpuThreads)
			mem = round(int(host.hardware.memorySize)/(1024*1024))

			# Save the greatest value
			if cpu > saved_cpu:
				saved_cpu = cpu
			if mem > saved_memory:
				saved_memory = mem

		# Check results and raise error if overallocation exist	
		if args['cpu'] > saved_cpu:
			raise Exception(f"Not enouh CPU threads to allocate. Maximum: {saved_cpu}")
		if args['ram'] > saved_memory:
			raise Exception(f"Not enouh RAM to allocate. Maximum: {saved_memory}")
		if args['disk'] > free_disk:
			raise Exception(f"Not enouh Disk to allocate. Maximum: {free_disk}")
		return True

	def create_vswitch(self, host, args):
		'''Create new virtual switch'''

		# Fetch variables from dictionary
		name = args['name']
		mtu = args['mtu']

		# Define specifications
		vss_spec = vim.host.VirtualSwitch.Specification()
		vss_spec.numPorts = 1024
		vss_spec.mtu = mtu

		# Perform creation task
		try:
			host.configManager.networkSystem.AddVirtualSwitch(vswitchName=name, spec=vss_spec)
			print(f"{host.name} Successfully created switch: {name}")
		except Exception as e:
			if e.msg:
				print(e.msg)
			else:
				print(e)

	def create_portgroup(self, host, args):
		'''Create portgroup and attach to vSwitch'''

		# Fetch variables from dictionary
		vssname = args['name']
		vlan = args['vlan']
		pgname = args['port_group']

		# Define specifications
		portgroup_spec = vim.host.PortGroup.Specification()
		portgroup_spec.vswitchName = vssname
		portgroup_spec.name = pgname
		portgroup_spec.vlanId = int(vlan)
		network_policy = vim.host.NetworkPolicy()
		network_policy.security = vim.host.NetworkPolicy.SecurityPolicy()
		network_policy.security.allowPromiscuous = True
		network_policy.security.macChanges = False
		network_policy.security.forgedTransmits = False
		portgroup_spec.policy = network_policy

		# Perform creation task
		try:
			host.configManager.networkSystem.AddPortGroup(portgroup_spec)
			print(f"{host.name} Successfully created portgroup: {pgname}")
		except Exception as e:
			if e.msg:
				print(e.msg)
			else:
				print(e)

	def create_vm(self, args):
		'''Function that creates a virtual machine'''

		# Get environment resources
		vm_folder = self.get_obj([vim.Folder], 'vm')
		resource_pool = self.get_obj([vim.ResourcePool], 'Resources')
		datastore = '[NFSstore] ' + args['name']

		# Define specifications
		vmx_file = vim.vm.FileInfo(logDirectory=None,
									snapshotDirectory=None,
									suspendDirectory=None,
									vmPathName=datastore)
		vm_spec = vim.vm.ConfigSpec()
		vm_spec.name = args['name']
		vm_spec.numCPUs = args['cpu']
		vm_spec.memoryMB = args['ram']
		vm_spec.files = vmx_file
		
		# Perform creation task
		try:
			print("Creating VM ...")
			task = vm_folder.CreateVM_Task(config=vm_spec, pool=resource_pool)
			WaitForTask(task)
			print("Successfully created VM:", args['name'])
		except Exception as e:
			print(e)

	def add_nic(self, vm, network):
		'''Function that adds a NIC to the VM and connects it to the portgroup'''

		# Define specifications
		spec = vim.vm.ConfigSpec()
		nic_changes = []
		nic_spec = vim.vm.device.VirtualDeviceSpec()
		nic_spec.operation = vim.vm.device.VirtualDeviceSpec.Operation.add
		nic_spec.device = vim.vm.device.VirtualE1000()
		nic_spec.device.deviceInfo = vim.Description()
		nic_spec.device.deviceInfo.summary = 'vCenter API test'
		nic_spec.device.backing =  vim.vm.device.VirtualEthernetCard.NetworkBackingInfo()
		nic_spec.device.backing.useAutoDetect = False
		nic_spec.device.backing.deviceName = network.name
		nic_spec.device.connectable = vim.vm.device.VirtualDevice.ConnectInfo()
		nic_spec.device.connectable.startConnected = True
		nic_spec.device.connectable.allowGuestControl = True
		nic_spec.device.connectable.connected = False
		nic_spec.device.connectable.status = 'untried'
		nic_spec.device.wakeOnLanEnabled = True
		nic_spec.device.addressType = 'assigned'
		nic_changes.append(nic_spec)
		spec.deviceChange = nic_changes

		# Perform creation task
		try:
			print("Attaching VM to portgroup ...")
			task = vm.ReconfigVM_Task(spec=spec)
			WaitForTask(task)
			print("Successfully added VM to portgroup.")
		except Exception as e:
			print(e)

	def clone_vm(self, template, vm_name):
		'''Function that deploy a VM from an existing template'''

		# Get environment resources
		template_resources = conn.get_obj([vim.VirtualMachine])
		template = None
		for temp in template_resources:
			if temp.name == template:
				template = temp
		if not template:
			raise Exception("Template not found.")
		vm_folder = self.get_obj([vim.Folder], 'vm')
		resource_pool = self.get_obj([vim.ResourcePool], 'Resources')
		datastore = self.get_obj([vim.Datastore], 'NFSstore')

		# Define specifications
		vmconf = vim.vm.ConfigSpec()
		relospec = vim.vm.RelocateSpec()
		relospec.datastore = datastore
		relospec.pool = resource_pool
		clonespec = vim.vm.CloneSpec()
		clonespec.location = relospec

		# Perform creation task
		try:
			print("Cloning VM...")
			task = template.Clone(folder=vm_folder, name=vm_name, spec=clonespec)
			WaitForTask(task)
			print("Cloning succesfull!")
		except Exception as e:
			print(e)
		
if __name__ == '__main__':

	# Get args
	try:
		args = get_args()
		conn_args = get_conn_args()
	except Exception as e:
		print("Invalid arguments passed to script:\n", e)
		sys.exit()

	# Establish connection to server and get hosts
	conn = ServerConnection(conn_args)
	hosts = conn.get_obj([vim.HostSystem])

	# Create VM
	if args['action'] == 'vm':
		if args['template']:
			try:
				conn.clone_vm(args['template'],args['name'])
			except Exception as e:
						print(e)
		else:
			try:
				if conn.check_hardware(hosts, args) == True:
					network = conn.get_obj([vim.Network], args['port_group'])
					conn.create_vm(args)
					vm = conn.get_obj([vim.VirtualMachine], args['name'])
					conn.add_nic(vm, network)
			except Exception as e:
				print(e)

	# Create switch
	elif args['action'] == 'switch':
		for host in hosts:
			conn.create_vswitch(host, args)
			conn.create_portgroup(host, args)

	# Finish up
	conn.disconnect()
	print("\nScript complete...")
