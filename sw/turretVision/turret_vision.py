import io
import argparse
import cv2
import math
import sys


parser = argparse.ArgumentParser()
parser.add_argument("serial", type=str, default='/dev/ttyACM0') 
parser.add_argument("-c", "--camera", type=int, default=1) 
parser.add_argument("--xoffset", type=int, default=10) 
parser.add_argument("--yoffset", type=int, default=-12) 
ARGS = parser.parse_args()

WIDTH = 640
HEIGHT = 480

MIN_VELOCITY = 11

CONTROLFILE = io.open(ARGS.serial, mode='wt')

def move_x(deviation):

    f_pos = deviation / WIDTH

    f_pos = -0.5 if f_pos < -0.5 else 0.5
    velocity = -f_pos * 200

    if velocity < 0 and velocity > -MIN_VELOCITY:
        velocity = -MIN_VELOCITY
    elif velocity > 0 and velocity < MIN_VELOCITY:
        velocity  = MIN_VELOCITY

    CONTROLFILE.write(u"qik 0 mov %s \n" % velocity)
    print("qik 0 mov %s \n" % velocity)

def move_y(deviation):

    f_pos = deviation / HEIGHT

    f_pos = -0.5 if f_pos < -0.5 else 0.5
    velocity = -f_pos * 200

    if velocity < 0 and velocity > -MIN_VELOCITY:
        velocity = -MIN_VELOCITY
    elif velocity > 0 and velocity < MIN_VELOCITY:
        velocity  = MIN_VELOCITY

    CONTROLFILE.write(u"qik 1 mov %s \n" % velocity)
    print("qik 1 mov %s \n" % velocity)

def main():

    x_center = WIDTH/2
    y_center = HEIGHT/2

    cap = cv2.VideoCapture(1)

    if not cap.isOpened():
        print("Capture could not be opened successfully.")

    while (True):

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

        _, frame = cap.read()

        time_on_target = 0
        time_before_relock = 0

        #Convert to grayscale
        frame = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)

        #Convert to binary black/white
        frame = cv2.adaptiveThreshold(frame, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,\
                       cv2.THRESH_BINARY, 11, 2)
        # _, frame = cv2.threshold(frame, 127, 255, cv2.THRESH_BINARY_INV)
        #frame = cv2.adaptiveThreshold(frame, 255, cv2.ADAPTIVE_THRESH_MEAN_C,\
        #                cv2.THRESH_BINARY, 11, 2)


        #Blur image to reduce noice
        cv2.medianBlur(frame, 5, frame)

        #Find circles
        max_radius = 25
        min_radius = 5
        
        circles = cv2.HoughCircles(frame, cv2.cv.CV_HOUGH_GRADIENT, 2, 100,
                        minRadius=min_radius,maxRadius=max_radius)

        frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2RGB)

        #If light in frame flickers, time to remain on the target
        if time_on_target > 0:
            time_on_target -= 1

        track_circle_dist = None
        #If we are currently tracking a target, draw it.
        if time_before_relock > 0 and track_circle_dist < 1000:
            cv2.circle(frame, (x_center, y_center), track_circle_dist, (128, 128, 128))
            
            #Decrement to tell us when we should give up and find a new target.
            time_before_relock -= 1
        else:
            #Reset to large circle and begin search again.
            track_circle_dist = 1000

        closest_circle = None
        close_circle_dist = sys.maxint
        #For some reason, circles is nested.
        if circles is not None:
            for c in circles[0]:
           
                x, y, radius = c.tolist()

                dist_from_center = distance_from_center(x-x_center,y-y_center) 
                if dist_from_center < close_circle_dist:
                    close_circle_dist = dist_from_center
                    closest_circle = c
            
            cv2.circle(frame, (int(x), int(y)), int(radius), (255, 51, 51), thickness=10)

        track_circle_dist = 0
        #Conditionals for moving tracking circle
        if time_before_relock != 0 and track_circle_dist < close_circle_dist:
            circles = None
        
        elif time_before_relock != 0 and track_circle_dist > close_circle_dist:
            track_circle_dist = close_circle_dist * 1.4
            time_before_relock = 20
        
        elif time_before_relock == 0:
            track_circle_dist = close_circle_dist * 1.4
            time_before_relock = 10
       
        if track_circle_dist < 20:
            track_circle_dist = 20

        if circles != None:
        
            x, y, radius = closest_circle
            print("x: %s, y: %s, deviation: %s" % (x, y, x-x_center))

            if is_in_circle(x, y, x_center, y_center, radius):
                CONTROLFILE.write(u"laser 1\n")
                print("Shoot!")

                #Will shoot for the next 10 frames.
                time_on_target = 10
            #If we aren't within the acceptable area for shooting (centeredish)
            else:
                if time_on_target == 0:
                    CONTROLFILE.write(u"laser 0\n")

                #Should move if not centered.
                if x < (x_center - radius/2) or x > (x_center + radius/2):
                    move_x(x_center-x)
                else:
                    move_x(0)

                if y < (y_center - radius/2) or y > (y_center + radius/2):
                    move_y(y_center-y)
                else:
                    move_x(0)

            cv2.circle(frame, (x, y), radius, (0, 0, 0))
            cv2.circle(frame, (x, y), 2, (0, 0, 0))
            
        else:
            
            CONTROLFILE.write(u"qik 0 move 0\n")
            CONTROLFILE.write(u"qik 1 move 0\n")
        
        cv2.imshow('frame', frame)


    CONTROLFILE.write(u"laser 0\n")

    #Stop motors
    CONTROLFILE.write(u"qik 0 mov 0\n")
    CONTROLFILE.write(u"qik 1 mov 0\n")
    
    CONTROLFILE.write(u"qik 0 coast\n")
    CONTROLFILE.write(u"qik 1 coast\n")

def is_in_circle(x1, y1, x2, y2, radius):            
           
    x_diff = x1-x2
    y_diff = y1-y2
    
    #Want to decrease the acceptable radius length so that the frame will shift
    #more towards the circle and make the laser more accurate.
    return math.sqrt(x_diff**2 + y_diff**2) < radius/2


def distance_from_center(x_dist, y_dist):
    '''Euclidean distance from center of a frame.'''
    return math.sqrt(x_dist**2 + y_dist**2)

main()
