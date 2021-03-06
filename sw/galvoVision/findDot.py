#!/usr/bin/python

import argparse
import cv2
import numpy as np
import math
import timeit

def nothing(x):
    pass

im1 = cv2.imread("testData/f1.png")
im2 = cv2.imread("testData/f2.png")
im3 = cv2.absdiff(im1, im2)

def findDot(image, squareSize, stepSize):
    shape = image.shape
    cols = shape[1]
    rows = shape[0]

    maxRow = 0
    maxCol = 0
    maxVal = 0

    for col in range(0, cols, stepSize):
        for row in range(0, rows, stepSize):
            sumElems = cv2.sumElems(image[row:(row + squareSize), col:(col + squareSize)])[0]
            if sumElems > maxVal:
                maxRow = row
                maxCol = col
                maxVal = sumElems

    return (maxCol, maxRow)

def constrain(point, lBound, uBound):
    newPoint = []
    for index in range(len(point)):
        if point[index] < lBound:
            newPoint.append(lBound)
        elif point[index] > uBound:
            newPoint.append(uBound)
        else:
            newPoint.append(point[index])

    return tuple(newPoint)


def findZeDot(gray):
    numCols = gray.shape[1]
    numRows = gray.shape[0]

    # 
    #  Find general area (200x200px) where dot is
    # 
    tmpImage = gray
    squareSize = 200
    maxCol, maxRow = findDot(tmpImage, squareSize, squareSize)
    print "Maximum at: (", maxCol, ",", maxRow, ")"
    cv2.rectangle(im3, (maxCol, maxRow), (maxCol + squareSize, maxRow + squareSize), (0,0,255), 1)

    # 
    # Compute new search area (10% larger in case we caught the dot in an edge)
    # 
    fudge = int(squareSize * 0.1)
    newRows = constrain((maxRow - fudge, maxRow + squareSize + fudge), 0, numRows)
    newCols = constrain((maxCol - fudge, maxCol + squareSize + fudge), 0, numCols)
    cv2.rectangle(im3, (newCols[0], newRows[0]), (newCols[1], newRows[1]), (0,0,128), 1)

    # 
    # Narrow down to a 20x20px area
    # 
    tmpImage = gray[newRows[0]:newRows[1], newCols[0]:newCols[1]] # Only needed for profiling
    squareSize = 20
    maxCol, maxRow = findDot(tmpImage, squareSize, squareSize)
    maxCol += newCols[0]
    maxRow += newRows[0]
    print "Maximum at: (", maxCol, ",", maxRow, ")"
    cv2.rectangle(im3, (maxCol, maxRow), (maxCol + squareSize, maxRow + squareSize), (0,255,0), 1)

    # 
    # Compute new search area (50% larger in case we caught the dot in an edge)
    # 
    fudge = int(squareSize * 0.5)
    newRows = constrain((maxRow - fudge, maxRow + squareSize + fudge), 0, numRows)
    newCols = constrain((maxCol - fudge, maxCol + squareSize + fudge), 0, numCols)
    cv2.rectangle(im3, (newCols[0], newRows[0]), (newCols[1], newRows[1]), (0,128,0), 1)

    # 
    # Narrow down to a 5x5px area and move by 1 pixel for better resolution
    # 
    tmpImage = gray[newRows[0]:newRows[1], newCols[0]:newCols[1]] # Only needed for profiling
    squareSize = 5
    maxCol, maxRow = findDot(tmpImage, squareSize, 1)
    maxCol += newCols[0]
    maxRow += newRows[0]
    print "Maximum at: (", maxCol, ",", maxRow, ")"
    cv2.rectangle(im3, (maxCol, maxRow), (maxCol + squareSize, maxRow + squareSize), (0, 0, 0), 1)

    return (int(maxCol + squareSize/2),int(maxRow + squareSize/2))

gray = cv2.cvtColor(im3, cv2.COLOR_BGR2GRAY)
_, gray = cv2.threshold(gray, 127, 255, cv2.THRESH_TOZERO)

x, y = findZeDot(gray)
# print x, y
cv2.circle(im3, (x, y), 4, [0,0,255])
cv2.imshow('image', im3)

cv2.waitKey()
