#!/usr/bin/python
import logging
import time
import uuid
import os
import pexpect
import optparse
import time
from intelhex import IntelHex

import Adafruit_BluefruitLE


# Enable debug output.
#logging.basicConfig(level=logging.DEBUG)

# Define service and characteristic UUIDs used by the UART service.
DFU_SERVICE_UUID = uuid.UUID('00001530-1212-EFDE-1523-785FEABCD123')
PKT_CHAR_UUID      = uuid.UUID('00001532-1212-EFDE-1523-785FEABCD123')
CPT_CHAR_UUID      = uuid.UUID('00001531-1212-EFDE-1523-785FEABCD123')

# Get the BLE provider for the current platform.


# DFU Opcodes
class Commands:
    START_DFU = chr(0x01) + chr(0x04)
    INITIALIZE_DFU = 2
    RECEIVE_FIRMWARE_IMAGE = 3
    VALIDATE_FIRMWARE_IMAGE = 4
    ACTIVATE_FIRMWARE_AND_RESET = 5
    SYSTEM_RESET = 6 

def convert_uint32_to_array(value):
    """ Convert a number into an array of 4 bytes (LSB). """
    return [
        (value >> 0 & 0xFF), 
        (value >> 8 & 0xFF), 
        (value >> 16 & 0xFF), 
        (value >> 24 & 0xFF)
    ] 

def convert_uint16_to_array(value):
    """ Convert a number into an array of 2 bytes (LSB). """
    return [
        (value >> 0 & 0xFF), 
        (value >> 8 & 0xFF)
    ] 

def convert_array_to_hex_string(arr):
    hex_str = ""
    for val in arr:
        if val > 255:
            raise Exception("Value is greater than it is possible to represent with one byte")
        hex_str = hex_str + chr(val) 
    return hex_str 

class BleDfuUploader(object):

	ctrlpt_handle = 0x0d
	ctrlpt_cccd_handle = 0x0e
	data_handle = 0x0b
	received_notify = 0


	def __init__(self, hexfile_path):
		self.hexfile_path = hexfile_path


    # Connect to peer device.
	def scan_and_connect(self):
		# Clear any cached data because both bluez and CoreBluetooth have issues with
		# caching data and it going stale.
		ble.clear_cached_data()

		# Get the first available BLE network adapter and make sure it's powered on.
		self.adapter = ble.get_default_adapter()
		print('Using adapter: {0}'.format(self.adapter.name))
		self.adapter.power_on()

		# Disconnect any currently connected UART devices.  Good for cleaning up and
		# starting from a fresh state.
		print('Disconnecting any connected DFU devices...')
		ble.disconnect_devices([DFU_SERVICE_UUID])

		# Scan for UART devices.
		print('Searching for DFU device...')
		try:
			self.adapter.start_scan()
			# Search for the first UART device found (will time out after 60 seconds
			# but you can specify an optional timeout_sec parameter to change it).
			self.device = ble.find_device(service_uuids=[DFU_SERVICE_UUID])
			if self.device is None:
				raise RuntimeError('Failed to find DFU device!')
		finally:
			# Make sure scanning is stopped before exiting.
			self.adapter.stop_scan()

		print('Connecting to device...')
		self.device.connect()  
		
		print('Discovering services...')
		self.device.discover([DFU_SERVICE_UUID], [PKT_CHAR_UUID, CPT_CHAR_UUID])

		self.dfu = self.device.find_service(DFU_SERVICE_UUID)
		self.cpt = self. dfu.find_characteristic(CPT_CHAR_UUID)
		self.pkt = self.dfu.find_characteristic(PKT_CHAR_UUID)
    
	def _dfu_state_set(self, opcode):
		self.cpt.write_value(chr(opcode))

	def _dfu_data_send(self, data_arr):
		hex_str = convert_array_to_hex_string(data_arr)
		self.pkt.write_value(hex_str)

	def _dfu_enable_cccd(self):
		cccd_enable_value_array_lsb = convert_uint16_to_array(0x0001)
		cccd_enable_value_hex_string = convert_array_to_hex_string(cccd_enable_value_array_lsb) 
		self.cpt.write_value(cccd_enable_value_hex_string)
		print "writing"
		
	def dfu_send_image(self):

		# Open the hex file to be sent
		ih = IntelHex(self.hexfile_path)
		bin_array = ih.tobinarray()

		hex_size = len(bin_array)
		print "Hex file size: ", hex_size
		string_size=8*chr(0x00) + convert_array_to_hex_string(convert_uint16_to_array(hex_size)) + 2*chr(0x00)
		#print repr(string_size)

		# Enable Notifications - Setting the DFU Control Point CCCD to 0x0001
		#self._dfu_enable_cccd()
		self.cpt.start_notify(self.received)
		
		time.sleep(0.1)

		# Sending 'START DFU' Command
		self.cpt.write_value(Commands.START_DFU)
		time.sleep(0.1)
		self.received_notify = 0
		self.pkt.write_value(string_size)
		while (self.received_notify == 0):
			time.sleep(0.001)
		
		self.cpt.write_value(chr(0x08)+chr(0x0c)+chr(0x00))
		time.sleep(0.1)
		self.cpt.write_value(chr(0x03))
		time.sleep(0.1)
		
		# Send hex file data packets
		chunk = 0
		self.received_notify = 0
		for i in range(0, hex_size, 20):
			data_to_send = bin_array[i:i + 20]
			self._dfu_data_send(data_to_send)
			time.sleep(0.01)
			print "Chunk #", chunk                                                      
			chunk += 1
			if (chunk%15==0):
				while (self.received_notify == 0):
					time.sleep(0.001)
				self.received_notify == 0
		self.received_notify == 0
		while (self.received_notify == 0):
			time.sleep(0.001)
		time.sleep(0.1)
		self.received_notify == 0
		self.cpt.write_value(chr(0x04))
		while (self.received_notify == 0):
			time.sleep(0.001)
		self.cpt.write_value(chr(0x05))
		time.sleep(0.1)
		
		# Send Validate Command
		self._dfu_state_set(Commands.VALIDATE_FIRMWARE_IMAGE)

		# Wait a bit for copy on the peer to be finished
		time.sleep(1)

		# Send Activate and Reset Command
		self._dfu_state_set(Commands.ACTIVATE_FIRMWARE_AND_RESET)

	# Disconnect from peer device if not done already and clean up. 
	def disconnect(self):
		self.device.disconnect()

	def received(self, data):
		self.received_notify = 1
		#print('Received: {0}'.format(repr(data)))


ble = Adafruit_BluefruitLE.get_provider()

ble.initialize()

if __name__ == '__main__':
    try:
        parser = optparse.OptionParser(usage='%prog -f <hex_file> \n\nExample:\n\ota.py -f blinky.hex',
                                       version='0.1')

        parser.add_option('-f', '--file',
                  action='store',
                  dest="hex_file",
                  type="string",
                  default=None,
                  help='Hex file to be uploaded.'
                  )

        options, args = parser.parse_args()

    except Exception, e:
        print e
        print "For help use --help"
        sys.exit(2)

    if (not options.hex_file):
        parser.print_help()
        exit(2)

    if not os.path.isfile(options.hex_file):
        print "Error: Hex file not found!"
        exit(2) 

def main():
	ble_dfu = BleDfuUploader(options.hex_file)
	ble_dfu.scan_and_connect()
	ble_dfu.dfu_send_image()

# Start the mainloop to process BLE events, and run the provided function in
# a background thread.  When the provided main function stops running, returns
# an integer status code, or throws an error the program will exit.
ble.run_mainloop_with(main)

