#!/usr/bin/python

import sys
import io
import threading
import Queue
import time
import signal

def signal_handler(signal, frame):
	print "exiting"
	sys.exit(0)

#
# Read serial stream and add lines to shared queue
#
class serialReadThread(threading.Thread):
	def __init__(self,device):
		super(serialReadThread, self).__init__()
		self.stream = io.open(device, 'r')
		self.running = 1
		print "opening ", device
		# TODO - add check in case file couldn't be openend

	def run(self):
		while self.running:
			line = self.stream.readline();
			inQueueLock.acquire()
			inQueue.put(line)
			inQueueLock.release()

#
# Write serial stream and add lines to shared queue
#
class serialWriteThread(threading.Thread):
	def __init__(self,device):
		super(serialWriteThread, self).__init__()
		self.stream = io.open(device, 'w')
		self.running = 1
		print "opening ", device
		# TODO - add check in case file couldn't be openend

	def run(self):
		while self.running:
			if not outQueue.empty():
				outQueueLock.acquire()
				line = unicode(outQueue.get())
				self.stream.write(line)
				outQueueLock.release()
			else :
				time.sleep(0.001)

	def write(self, line):
		outQueueLock.acquire()
		outQueue.put(line)
		outQueueLock.release()

#
# Process lines coming from targetController via USB-serial link
#
def processLine(line):
	global targets
	args = line.split()

	if len(args) > 1:
		if args[1] == "connected":
			targetID = int(args[0])
			print "Target", targetID , "is connected"
			targetLock.acquire()
			targets[targetID] = True
			targetLock.release()
		elif args[1] == "hit":
			targetID = int(args[0])
			print "Target", targetID, "hit!"
			if targetID in targets:
				targetLock.acquire()
				targets[targetID] = False
				targetLock.release()
		else:
			print "controller: ", line,

#
# Go through each target and check if they've been hit
# If they're all hit, exit
#
def checkTargets():
	if(len(targets) > 0):
		notDone = 0

		targetLock.acquire()
		for key in targets.keys():
			if targets[key] == True:
				notDone = 1
		targetLock.release()

		if notDone == 0:
			global done
			done = 1
			print "All targets hit!"

# 
#  Start here :D
# 
if not len(sys.argv) > 1:
	print "Usage: " + sys.argv[0] + " </dev/serialdevicename>"
	sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

print "Press Ctrl + C to exit"

inQueueLock = threading.Lock()
inQueue = Queue.Queue()

outQueueLock = threading.Lock()
outQueue = Queue.Queue()

targetLock = threading.Lock()

targets = {}
done = 0

# Start readThread as daemon so it will automatically close on program exit
readThread = serialReadThread(sys.argv[1])
readThread.daemon = True
readThread.start()

# Start writeThread as daemon so it will automatically close on program exit
writeThread = serialWriteThread(sys.argv[1])
writeThread.daemon = True
writeThread.start()

# Start scan for connected targets
writeThread.write("init\n")

# Enable targets and wait for hits
writeThread.write("start\n")

while not done:
	if not inQueue.empty():
		inQueueLock.acquire()
		line = inQueue.get()
		inQueueLock.release()

		# Process line here
		# We could probably do this in the readThread, leaving here for now
		processLine(line)

	else:
		# Sleep so CPU doesn't spin at 100%
		# TODO - add nicer blocking
		time.sleep(0.001)

	checkTargets()

sys.exit(0)
