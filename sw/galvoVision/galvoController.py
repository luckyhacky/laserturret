import numpy as np
import threading
import serial
import math
import time
import copy
import csv
import sys
import os

class serialReadThread(threading.Thread):
    def __init__(self, inStream):
        super(serialReadThread, self).__init__()

        self.stream = inStream
        self.running = 1

    def run(self):
        while self.running:
            try:
                line = self.stream.readline(50)
                if line:
                    print line
            except serial.SerialException:
                print "serial error"

class galvoController():
    def __init__(self, streamFileName = None, shotDelay = 0.01):

        if streamFileName:
            self.stream = serial.Serial(streamFileName)

            # Start readThread as daemon so it will automatically close on program exit
            self.readThread = serialReadThread(self.stream)
            self.readThread.daemon = True
            self.readThread.start()

        self.shotDelay = shotDelay
        self.lastShotTime = time.time()
        self.dotTable = []

    def loadDotTable(self,filename):
        # 
        # Read table into list of lists (i think)
        # Format is "laserX, laserY, pixelX, pixelY"
        # 
        with open(filename, 'rb') as csvfile:
            reader = csv.reader(csvfile, delimiter=',')
            for row in reader:
                # Ignore bad values
                if int(row[2]) > 0 and int(row[3]) > 0:
                    self.dotTable.append([int(row[0]), int(row[1]), int(row[2]), int(row[3])])

    def setLaserState(self, state):
        if(state):
            self.stream.write('laser 1\n')
        else:
            self.stream.write('laser 0\n')

    def setLaserPos(self, x, y):
        self.stream.write("g 0 " + str(x) + "\n")
        self.stream.write("g 1 " + str(y) + "\n")

    def laserShoot(self, target = '*', id = '00'):
        now = time.time()
        if now > (self.lastShotTime + self.shotDelay):
            self.stream.write('s [' + target + 'I' + id + ']\n')
            self.lastShotTime = now

    def addMidPoints(self, pointList, dupeThreshold = 5):
        newPointList = copy.copy(pointList)
        for p1 in pointList:
            for p2 in pointList:
                
                # Remove complete duplicates
                if p1 == p2:
                    continue

                midPoint = self.getMidPoint((p1[2], p1[3]), (p2[2], p2[3]))
                midLaserPoint = self.getMidPoint((p1[0], p1[1]), (p2[0], p2[1]))
                
                # Check against all other points, if they are within dupeThreshold, don't add the new one
                dist = 1e99
                for p3 in newPointList:
                     dist = self.getDist((midPoint[0], midPoint[1]), (p3[2], p3[3]))
                     if dist < dupeThreshold:
                        break

                # This is a new point, add it!
                if dist >= dupeThreshold:
                    newPointList.append([midLaserPoint[0], midLaserPoint[1], midPoint[0], midPoint[1]])

        return newPointList

    def getMidPoint(self, p1, p2):
        return int((p1[0] + p2[0])/2), int((p1[1] + p2[1])/2)

    def getDist(self, p1, p2):
        return math.sqrt(math.pow((p1[0] - p2[0]),2) + math.pow((p1[1] - p2[1]),2))

    def getClosestPoints(self, pointList, point, nPoints = 4):
        distTable = []

        pixelX = point[0]
        pixelY = point[1]

        # 
        # Get distance from every calibration point to pixelX, pixelY
        # 
        for index in range(len(pointList)):
            dotX = pointList[index][2]
            dotY = pointList[index][3]

            # Don't include if it's an exact match
            # if dotX == pixelX and dotY == pixelY:
                # continue

            dist = self.getDist((pixelX, pixelY), (dotX, dotY))
            distTable.append([index, dist])    

        sortedDistTable = sorted(distTable, key = lambda x:x[1])

        newTable = []
        for item in sortedDistTable[0:nPoints]:
            newTable.append(pointList[item[0]])
        
        return newTable

    def getLaserPos(self, pixelX, pixelY):
        # Get the four closest points
        points = self.getClosestPoints(self.dotTable, (pixelX, pixelY), 4)

        # Interpolate between them to get new mid-points (with mid laser values calculated too)
        points = self.addMidPoints(points)

        # Repeat with the new list (including virtual points)
        points = self.getClosestPoints(points, (pixelX, pixelY), 4)

        # Add more virtual points!
        points = self.addMidPoints(points)

        # And again...
        points = self.getClosestPoints(points, (pixelX, pixelY), 4)

        points = self.addMidPoints(points, dupeThreshold = 4)

        # and again
        points = self.getClosestPoints(points, (pixelX, pixelY), 4)

        points = self.addMidPoints(points, dupeThreshold = 2)

        # Get final closest point
        points = self.getClosestPoints(points, (pixelX, pixelY), 1)
        return points[0]
