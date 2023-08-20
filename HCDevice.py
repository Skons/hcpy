#!/usr/bin/env python3
# Parse messages from a Home Connect websocket (HCSocket)
# and keep the connection alive
#
# Possible resources to fetch from the devices:
#
# /ro/values
# /ro/descriptionChange
# /ro/allMandatoryValues
# /ro/allDescriptionChanges
# /ro/activeProgram
# /ro/selectedProgram
#
# /ei/initialValues
# /ei/deviceReady
#
# /ci/services
# /ci/registeredDevices
# /ci/pairableDevices
# /ci/delregistration
# /ci/networkDetails
# /ci/networkDetails2
# /ci/wifiNetworks
# /ci/wifiSetting
# /ci/wifiSetting2
# /ci/tzInfo
# /ci/authentication
# /ci/register
# /ci/deregister
#
# /ce/serverDeviceType
# /ce/serverCredential
# /ce/clientCredential
# /ce/hubInformation
# /ce/hubConnected
# /ce/status
#
# /ni/config
#
# /iz/services

import sys
import json
import re
import time
import io
import traceback
from datetime import datetime
from base64 import urlsafe_b64encode as base64url_encode
from Crypto.Random import get_random_bytes


def now():
	return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")

class HCDevice:
	def __init__(self, ws, features, name, description):
		self.ws = ws
		self.features = features
		self.session_id = None
		self.tx_msg_id = None
		self.device_name = "hcpy"
		self.device_id = "0badcafe"
		self.debug = False
		self.name = name
		self.description = description
		self.uids = {} #mapping of uids to features
		for uid in self.features: 
			feature = self.features[uid]
			feature_name = feature["name"]
			self.uids[feature_name] = int(uid)
		

	def parse_values(self, values):
		if not self.features:
			return values

		result = {}

		for msg in values:
			uid = str(msg["uid"])
			value = msg["value"]
			value_str = str(value)

#			name = uid
			status = None

			if uid in self.features:
				status = self.features[uid] 

			if status:
#				name = status["name"]
				if "values" in status \
				and value_str in status["values"]:
					value = status["values"][value_str]
#keep communication to HCDevice uid based. Formatting to human-readable names in hc2mqtt
#			# trim everything off the name except the last part
#			name = re.sub(r'^.*\.', '', name)
#			result[name] = value
			result[uid] = value

		return result
	
	def get_featureUID(self, feature_name):
		if feature_name not in self.uids:
			raise Exception("'{}' unknown feature_name. No UID found.")
		return self.uids[feature_name]
		
			
	# Test the uid used for a program of an appliance against available programs 
	# and Setting "BSH.Common.Setting.RemoteControlLevel"
	def test_and_reformat_program(self, data):
		#example json data content: {"program":8196, "options":[{"uid":558,"value":0},{"uid":5123,"value":false},{"uid":5126,"value":false},{"uid":5127,"value":false}]}  (thanks to @chris-mc1)
		#TODO check on options
		
		if 'program' not in data:
			raise Exception("{self.name}. Unable to configure appliance. 'program' is required.")
		
		if isinstance(data['program'], str) == True:
			try:
				data['program'] = int(data['program']) #try to transform into int
			except Exception as e:
				raise Exception("{self.name}. Unable to configure appliance. UID in 'program' must be an integer.")
		elif isinstance(data['program'], int) == False:
			raise Exception("{self.name}. Unable to configure appliance. UID in 'program' must be an integer.")
		
		# Check if the uid is a valid program for this appliance
		uid = str(data['program'])
		if uid not in self.features:
			raise Exception(f"{self.name}. Unable to configure appliance. UID {uid} is not valid.")
		feature = self.features[uid]
		if ".Program." not in feature['name']: #check is valid for dishwasher. TODO: check other devices
			raise Exception(f"{self.name}. Unable to configure appliance. UID {uid} is not a valid program.")
		
		if remoteControlStartAllowed is None or not remoteControlStartAllowed: #allow if none, if device has no remoteControlStartAllowed feature (or a different uid for it than used to detect remoteControlStartAllowed)
			#since this is not watched by the device itself
			raise Exception(f"{self.name}. Program not started. Remote access ist not activated on device. Check and change 'RemoteControlStartAllowed'.")
	
		return data

	# Test the feature of an appliance agains a data object
	def test_and_reformat_feature(self, data):
		#example json data content: {'uid': 539, 'value': 2}
		if 'uid' not in data:
			raise Exception("{self.name}. Unable to configure appliance. UID is required.")

		if isinstance(data['uid'], str) == True:
			try:
				data['uid'] = int(data['uid']) #try to transform into int
			except Exception as e:
				raise Exception("{self.name}. Unable to configure appliance. UID must be an integer.")
		elif isinstance(data['uid'], int) == False:
			raise Exception("{self.name}. Unable to configure appliance. UID must be an integer.")

		if 'value' not in data:
			raise Exception("{self.name}. Unable to configure appliance. Value is required.")

		# Check if the uid is present for this appliance
		uid = str(data['uid'])
		if uid not in self.features:
			raise Exception(f"{self.name}. Unable to configure appliance. UID {uid} is not valid.")

		feature = self.features[uid]

		# check the access level of the feature
		print(now(), self.name, f"Processing feature {feature['name']} with uid {uid}")
		if 'access' not in feature:
			raise Exception(f"{self.name}. Unable to configure appliance. Feature {feature['name']} with uid {uid} does not have access.")

		access = feature['access'].lower()
		if access != 'readwrite' and access != 'writeonly':
			raise Exception(f"{self.name}. Unable to configure appliance. Feature {feature['name']} with uid {uid} has got access {feature['access']}.")

		# check if selected list with values is allowed
		if 'values' in feature:
			value = None
			if isinstance(data['value'], int):
				#in difference to the comment below it has to be an integer (at least for dishwasher. TODO: check other devices)
				#value = str(data['value']) # values are strings in the feature list, but always seem to be an integer. An integer must be provided
				value = data['value']
				if str(value) not in feature['values']:
					raise Exception(f"{self.name}. Unable to configure appliance. Value {data['value']} is not a valid value. Allowed values are {feature['values']}.")
			elif isinstance(data['value'], str):
				for option in feature['values']:
					if feature['values'][option] == data['value']:
						value = int(option)
						break
			if value is None:
				raise Exception(f"Unable to configure appliance. The value {data['value']} must be an integer or a string . Allowed values are {feature['values']}.")
			else:
				data['value'] = value

		if 'min' in feature:
			min = int(feature['min'])
			max = int(feature['min'])
			if isinstance(data['value'], int) == False or data['value'] < min or data['value'] > max:
				raise Exception(f"{self.name}. Unable to configure appliance. Value {data['value']} is not a valid value. The value must be an integer in the range {min} and {max}.")

		return data

	def recv(self):
		try:
			buf = self.ws.recv()
			if buf is None:
				return None
		except Exception as e:
			print(self.name, "receive error", e, traceback.format_exc())
			return None

		try:
			return self.handle_message(buf)
		except Exception as e:
			print(self.name, "error handling msg", e, buf, traceback.format_exc())
			return None

	# reply to a POST or GET message with new data
	def reply(self, msg, reply):
		self.ws.send({
			'sID': msg["sID"],
			'msgID': msg["msgID"], # same one they sent to us
			'resource': msg["resource"],
			'version': msg["version"],
			'action': 'RESPONSE',
			'data': [reply],
		})
		

	# send a message to the device
	def get(self, resource, version=1, action="GET", data=None):
		msg = {
			"sID": self.session_id,
			"msgID": self.tx_msg_id,
			"resource": resource,
			"version": version,
			"action": action,
		}

		if data is not None:
			if action == "POST":
				#if self.test_feature(data) != True:
				#	return
				#msg["data"] = [data]
#				print("REMINDER WIEDER test_and_reformat_feature AKTIVIEREN")
#				msg["data"] = [data]
				if resource == "/ro/activeProgram":
					msg["data"] = [self.test_and_reformat_program(data)]
				elif resource == "/ro/values":
					msg["data"] = [self.test_and_reformat_feature(data)]
				else:
					print("Warning: for this resource no checks are performed on data")
					msg["data"] = [data]
			else:
				msg["data"] = [data]

		try:
			self.ws.send(msg)
		except Exception as e:
			print(self.name, "Failed to send", e, msg, traceback.format_exc())
		self.tx_msg_id += 1

	# same like get, but with POST as action default
	def post(self, resource, version=1, action="POST", data=None):
		self.get(resource, version, action, data)
	
	
	def handle_message(self, buf):
		msg = json.loads(buf)
		if self.debug:
			print(now(), self.name, "RX:", msg)
		sys.stdout.flush()

		resource = msg["resource"]
		action = msg["action"]

		values = {}

		if "code" in msg:
			print(now(), self.name, "ERROR", msg["code"])
			values = {
				"error": msg["code"],
				"resource": msg.get("resource", ''),
			}
		elif action == "POST":
			if resource == "/ei/initialValues":
				# this is the first message they send to us and
				# establishes our session plus message ids
				self.session_id = msg["sID"]
				self.tx_msg_id = msg["data"][0]["edMsgID"]

				self.reply(msg, {
					"deviceType": "Application",
					"deviceName": self.device_name,
					"deviceID": self.device_id,
				})

				# ask the device which services it supports
				self.get("/ci/services")

				if (self.description["type"] != "Dishwasher"): #TODO instead of != dishwasher change it to == clothwasehr - but to the name what it is actually(don't have one))
					# the clothes washer wants this, the token doesn't matter,
					# although they do not handle padding characters
					# they send a response, not sure how to interpet it
					token = base64url_encode(get_random_bytes(32)).decode('UTF-8')
					token = re.sub(r'=', '', token)
					self.get("/ci/authentication", version=2, data={"nonce": token})

				if (self.description["type"] != "Dishwasher"): #TODO instead of != dishwasher change it to == clothwasehr - but to what it actually belongs
					self.get("/ci/info", version=2)  # clothes washer
				if (self.description["type"] == "Dishwasher"):
					self.get("/iz/info")  # dish washer
				#self.get("/ci/tzInfo", version=2)
				if (self.description["type"] != "Dishwasher"): #TODO instead of != dishwasher change it to == clothwasehr - but to what it actually belongs
					self.get("/ni/info")
				#self.get("/ni/config", data={"interfaceID": 0})
				self.get("/ei/deviceReady", version=2, action="NOTIFY")
				#Note: allDescriptionChanges was twice. One commented out, since not necessary at least for dishwasher. Is it necessary for other devices?
				#self.get("/ro/allDescriptionChanges")
				self.get("/ro/allDescriptionChanges")
				self.get("/ro/allMandatoryValues")
				#self.get("/ro/values")
				#self.get("/ro/values")
			else:
				print(now(), self.name, "Unknown resource", resource, file=sys.stderr)

		elif action == "RESPONSE" or action == "NOTIFY":
			if resource == "/iz/info" or resource == "/ci/info":
				# we could validate that this matches our machine
				pass

			elif resource == "/ro/descriptionChange" \
			or resource == "/ro/allDescriptionChanges":
				# we asked for these but don't know have to parse yet
				pass

			elif resource == "/ni/info":
				# we're already talking, so maybe we don't care?
				pass

			elif resource == "/ro/allMandatoryValues" \
			or resource == "/ro/values":
				if 'data' in msg:
					values = self.parse_values(msg["data"])
				else:
					print(now(), self.name, f"received {action}: {msg}")
					
				if '517' in values:#uid for BSH.Common.Status.RemoteControlStartAllowed (at least for dishwasher)
					global remoteControlStartAllowed
					remoteControlStartAllowed = values['517'] 
				
			elif resource == "/ci/registeredDevices":
				# we don't care
				pass

			elif resource == "/ci/services":
				self.services = {}
				for service in msg["data"]:
					self.services[service["service"]] = {
						"version": service["version"],
					}
				#print(self.name, now(), "services", self.services)

				# we should figure out which ones to query now
#				if "iz" in self.services:
#					self.get("/iz/info", version=self.services["iz"]["version"])
#				if "ni" in self.services:
#					self.get("/ni/info", version=self.services["ni"]["version"])
#				if "ei" in self.services:
#					self.get("/ei/deviceReady", version=self.services["ei"]["version"], action="NOTIFY")

				#self.get("/if/info")

		else:
			print(now(), self.name, "Unknown", msg)

		# return whatever we've parsed out of it
		return values
