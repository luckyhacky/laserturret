import argparse
from itertools import compress
import os
from math import sqrt
import serial
from sys import maxint

import cv2
import cProfile
import numpy as np
import time

from galvoController import galvoController
from cameraReadThread import cameraReadThread

INIT_STATE = True
LOCKED_STATE = False
SHOOT_STATE = False
C_EXTENTS = None
FC_BOUNDS = None
PAST_CONTS = None
PAST_BLUES = None
LAST_SHOT_TIME = None
SCALE_FACTOR = 1080.0/720.0



def parse_args():

    parser = argparse.ArgumentParser()
    parser.add_argument("v_input", type=int,
                        help="Which camera should be used in case of multiple.")
    parser.add_argument('str_loc', help="Location of the serial stream file.")
    parser.add_argument('--template', help="Optional image to match on.")
    args = parser.parse_args()

    return args

def main():
    global INIT_STATE, LOCKED_STATE, SHOOT_STATE, C_EXTENTS, FC_BOUNDS
    global PAST_CONTS, PAST_BLUES, LAST_SHOT_TIME, SCALE_FACTOR

    args = parse_args()

    # cameraThread = cameraReadThread(args.v_input,
    #                                 width=int(1920/SCALE_FACTOR),
    #                                 height=int(1080/SCALE_FACTOR))
    # cameraThread.daemon = True
    # cameraThread.start()

    # exposure = 50

    os.system("v4l2-ctl -d " + str(args.v_input) + " -c focus_auto=0,exposure_auto=1")
    os.system("v4l2-ctl -d " + str(args.v_input) + " -c focus_absolute=0,exposure_absolute=" + str(exposure))


    controller = galvoController(args.str_loc, shotDelay=0.25)
    controller.loadDotTable('./workspace/laserturret/sw/galvoVision/dotTable.csv')
    controller.setLaserState(True)

    trgs_req_to_lock = 1
    trgs_total = 5


    cv2.namedWindow('image', cv2.WINDOW_NORMAL)
    cv2.namedWindow('masked', cv2.WINDOW_NORMAL)
    cv2.namedWindow('contours', cv2.WINDOW_NORMAL)

    fgbg = cv2.createBackgroundSubtractorMOG2(detectShadows=False)

    # while (True):
    #
    #     frame = cameraThread.getFrame()

    cap = cv2.VideoCapture('./workspace/laserturret/sw/galvoVision/moving_targets.avi')
    single = False

    while cap.isOpened():

        _, frame = cap.read()
        frame = cv2.resize(frame, (0, 0), fx=1/SCALE_FACTOR, fy=1/SCALE_FACTOR)

        movement_mask = fgbg.apply(frame)
        controller.laserShoot()

        if INIT_STATE:
            '''In init state, no suitable contours detected.
            ACTION: Search FULL image for contours.
            MOVES TO: LOCKED STATE
            CONDITION: Have at least trgs_req_to_lock contours which meet
                the target critiera.
            '''
            contours = all_feature_contours(movement_mask)
            n_contours = get_n_contours(contours, trgs_total)

            if len(n_contours) >= trgs_req_to_lock:
                shift_to_locked(n_contours)

            print "Leaving if init."

        elif LOCKED_STATE:
            '''Locked to trgs, n suitable contours detected.
            ACTION:
                - Clip incoming frame to a std size.
                - Continue to detect contours on smaller frame.
                - Follow targets
                - Get mean color of each known contour.
                >> Determine future location
                >> Determine alpha trg.
                >> Determine target order.
            MOVES TO: SHOOTING STATE
            CONDITION: Have alpha target, it's blue, and know what number it is.
            '''
            print "Entering if locked."

            # Slice needs to be y, x, starts at upper left corner.
            contours = all_feature_contours(
                movement_mask[FC_BOUNDS[2]:FC_BOUNDS[3],
                            FC_BOUNDS[0]:FC_BOUNDS[1]]
            )
            n_contours = get_n_contours(contours, trgs_total)

            # Lost the lock. Shift back to init.
            if not len(n_contours) >= trgs_req_to_lock:
                shift_to_init()

            # Make sure we continue to follow contour extents.
            # Possible that we just shifted to init in here, so need to check
            # before we correct according to new contours.n_contours =
            elif n_contours:
                correct_for_contour_movement(n_contours)
                blues = racial_profile(
                    frame[FC_BOUNDS[2]:FC_BOUNDS[3],
                    FC_BOUNDS[0]:FC_BOUNDS[1], ::],
                    n_contours
                )

                # If at least one target in the set is blue, shift to shoot.
                if sum(blues) >= 1:
                    shift_to_shoot(n_contours, blues)

            draw(frame, n_contours)

        elif SHOOT_STATE:
            ''' Locked to trgs, have ACTIVE trgs.
            ACTION:
                - IF we know where all all_trgs are, can call our shot.
                - ELSE, get the first blue, and shoot as wildcard.
                - Move back to init.
            MOVES TO: INIT STATE
            CONDITION: Always.
            '''
            # Want to keep track of frame's movement even though we're shooting this
            # frame.
            contours = all_feature_contours(
                movement_mask[FC_BOUNDS[2]:FC_BOUNDS[3],
                            FC_BOUNDS[0]:FC_BOUNDS[1]]
            )
            n_contours = get_n_contours(contours, trgs_total)

            # if len(n_contours) == trgs_total:
            #     idx, (c_x, c_y) = call_the_shot(n_contours)
            #
            #     setLaserPos(stream, c_x, c_y)
            #     # Have to add 1, because WTF STARTING ADDRESSING WITH 1.
            #     laserShoot(stream, target=str(idx+1))
            #
            # # If we aren't confident what's what, shoot as wildcard.
            # else:
            #     curr_trg = next(compress(PAST_CONTS, PAST_BLUES))
            #     c_x, c_y, _ = get_center(curr_trg)
            #
            #     setLaserPos(stream, c_x, c_y)
            #     laserShoot(stream)

            curr_trg = next(compress(PAST_CONTS, PAST_BLUES))
            c_x, c_y, r = get_center(curr_trg)
            cv2.circle(frame, (c_x, c_y), r, (0, 0, 255), 10)

            calib_pt = controller.getLaserPos(int(c_x*SCALE_FACTOR), int(c_y*SCALE_FACTOR))
            controller.setLaserPos(calib_pt[0], calib_pt[1])
            print "Laser shooting at {}, calibrated to {}".format((c_x, c_y), calib_pt)

            if n_contours:
                blues = racial_profile(
                    frame[FC_BOUNDS[2]:FC_BOUNDS[3],
                    FC_BOUNDS[0]:FC_BOUNDS[1], ::],
                    n_contours
                )
                if any(blues):
                    print "In shoot, staying in shoot. Have blues: %s" % blues
                    shift_to_shoot(n_contours, blues)
                else:
                    shift_to_locked(n_contours)
            else:
                shift_to_init()

        else:
            print "SOMETHING HAS GONE TERRIBLY WRONG."
            pass

        print "Made it to the end."
        cv2.imshow('image', frame)
        cv2.imshow('masked', movement_mask)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            controller.setLaserState(False)
            break


def call_the_shot(curr_n_contours):
    global PAST_CONTS, PAST_BLUES

    '''
    matched_coords- Of the form
        [[(prev_x, prev_y_y), (curr_x, curr_y), curr_radius, is_blue],
         [...], [...]]
    '''
    # Carrying blues in so that we don't have to color profile all over again.
    matched_pairs = \
        find_shortest_distances(curr_n_contours, PAST_CONTS, PAST_BLUES)
    print "Matched are {}".format(matched_pairs)

    alpha_center = determine_alpha_circle(matched_pairs)

    def distance(coord_sets):
        print "Coord set: {}".format(coord_sets)
        _, curr, _, _ = coord_sets
        return sqrt((alpha_center[0] - curr[0])**2 +
                    (alpha_center[1] - curr[1])**2)

    ordered_trgs = sorted(matched_pairs, key=distance)
    # "Give me the next target and the index relative to the alpha target whose
    # color is blue.
    # Return will be of the form (idx, (x, y))
    print "ORDERED trgs: {}".format(ordered_trgs)
    new_trg = \
        next((i, coord_set[1]) for i, coord_set in enumerate(ordered_trgs) if coord_set[3])

    return new_trg


def correct_for_contour_movement(contours):
    global FC_BOUNDS, C_EXTENTS, SCALE_FACTOR

    update_contour_extents(contours)

    print "Correcting, because C_Extents %s, but FC_BOUNDS %s" % (C_EXTENTS, FC_BOUNDS)
    far_right = 1919/SCALE_FACTOR
    far_bottom = 1079/SCALE_FACTOR

    # Left/Right check
    if C_EXTENTS[0] < FC_BOUNDS[0] or C_EXTENTS[1] > FC_BOUNDS[1]:
        FC_BOUNDS[0] = max(C_EXTENTS[0] - 100, 0)
        FC_BOUNDS[1] = min(C_EXTENTS[1] + 50, far_right)
    # # Right check
    # elif C_EXTENTS[1] > FC_BOUNDS[1]:
    #     FC_BOUNDS[1] = min(C_EXTENTS[1] + 50, 1919)
    #     FC_BOUNDS[0] += 50
    # Top/Bottom check
    elif C_EXTENTS[2] < FC_BOUNDS[2] or C_EXTENTS[3] > FC_BOUNDS[3]:
        FC_BOUNDS[2] = max(C_EXTENTS[2] - 100, 0)
        FC_BOUNDS[3] = min(C_EXTENTS[0] + 100, far_bottom)
    # # Bottom check
    # elif C_EXTENTS[3] > FC_BOUNDS[3]:
    #     FC_BOUNDS[3] = min(C_EXTENTS[0] + 50, 1079)
    #     FC_BOUNDS[2] += 50
    else:
        print "Didn't need to correct."
        pass


def update_contour_extents(n_contours):
    global C_EXTENTS

    leftmost = \
        min([tuple(cnt[cnt[:,:,0].argmin()][0])[0] for cnt in n_contours])
    rightmost = \
        max([tuple(cnt[cnt[:,:,0].argmax()][0])[0] for cnt in n_contours])
    topmost = \
        min([tuple(cnt[cnt[:,:,1].argmin()][0])[1] for cnt in n_contours])
    bottommost = \
        max([tuple(cnt[cnt[:,:,1].argmax()][0])[1] for cnt in n_contours])

    C_EXTENTS = [leftmost, rightmost, topmost, bottommost]


def shift_to_init():
    global INIT_STATE, LOCKED_STATE, SHOOT_STATE
    """
    Lost full set of targets. Go back to init state.
    """
    print "Shifting to INIT state."
    INIT_STATE = True
    LOCKED_STATE = False
    SHOOT_STATE = False


def shift_to_locked(contours):
    global INIT_STATE, LOCKED_STATE, C_EXTENTS, FC_BOUNDS
    """
    Input: Set of contours which are of appropriate size to be targets.
    Note: Move to locked state initializes the frame clip
    extents to be the contour extents, stretched by 500 and 250.
    """

    INIT_STATE = False
    LOCKED_STATE = True

    update_contour_extents(contours)
    print "C_Extents before changing FC: {}".format(C_EXTENTS)

    # Left, Right, Up, Down
    FC_BOUNDS = [max(C_EXTENTS[0] - 25, 0), min(C_EXTENTS[0] + 500, 1919),
                 max(C_EXTENTS[2] - 25, 0), min(C_EXTENTS[2] + 250, 1079)]
    print "Moved to LOCKED with window bounds: %s" % FC_BOUNDS


def shift_to_shoot(contours, blues):
    global LOCKED_STATE, SHOOT_STATE
    global PAST_CONTS, PAST_CORRECT, PAST_BLUES
    """
    Input: Full set of contours, and one happens to be blue.
    """
    correct_for_contour_movement(contours)

    LOCKED_STATE = False
    SHOOT_STATE = True

    PAST_CONTS = contours
    PAST_BLUES = blues


    print ("Shifting to shoot. Have blues: {}".format(blues))


def all_feature_contours(mask):
    global FC_BOUNDS
    global LOCKED_STATE

    cp = mask.copy()

    # Running w/ offset of None errored program out, so separating out func.
    if LOCKED_STATE or SHOOT_STATE:
        # Offset (left, top) b/c extracting from the greater frame.
        _, contours, hierarchy = \
            cv2.findContours(cp, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE,
                             offset=(FC_BOUNDS[0], FC_BOUNDS[2]))
    else:
        _, contours, hierarchy = \
            cv2.findContours(cp, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

    contours = [cv2.approxPolyDP(cnt, 3, True) for cnt in contours]

    return contours


def racial_profile(source_img, contours):
    global FC_BOUNDS

    # Passing in the sliced version of the frame, so need to subtract out
    # the offset.
    hsv_frame = cv2.cvtColor(source_img.copy(), cv2.COLOR_BGR2HSV)
    #cv2.imwrite('/home/kathryn/workspace/laserturret//sw/galvoVision/testData/baz_' + time.strftime("%Y%m%d-%H%M%S") + ".png", hsv_frame)

    lower_blue = np.array([105,50,20])
    upper_blue = np.array([130,255,255])

    def is_blue(img, cnt):

        mask = np.zeros(img.shape[:2], np.uint8)
        cv2.drawContours(mask, [cnt], 0, 255, -1,
                         offset=(-FC_BOUNDS[0], -FC_BOUNDS[2]))

        mean = cv2.mean(img, mask=mask)
        print "Mean color: {}".format(mean)

        foo = all((mean[:3] < upper_blue) & (lower_blue < mean[:3]))

        # if foo:
        #     cv2.imwrite('/home/kathryn/workspace/laserturret//sw/galvoVision/testData/foo_' + time.strftime("%Y%m%d-%H%M%S") + ".png", mask)
        #     cv2.imwrite('/home/kathryn/workspace/laserturret/sw/galvoVision/testData/bar_' + time.strftime("%Y%m%d-%H%M%S") + ".png", img)

        return foo

    return [is_blue(hsv_frame, cnt) for cnt in contours]


def draw(img_out, contours, future_pairs=None):
    global FC_BOUNDS
    """
    DRAW THE THING. And any additional things you want.
    """
    h, w = img_out.shape[:2]
    vis = np.zeros((h, w, 3), np.uint8)
    cv2.drawContours(vis, contours, -1, (128,255,255), 3, cv2.LINE_AA)

    draw_bounding_rect(vis, contours)
    if future_pairs:
        draw_the_future(vis, future_pairs)
    # draw_bounding_circle(vis, contours)

    # Show current search area.
    cv2.rectangle(vis,
                  (FC_BOUNDS[0], FC_BOUNDS[2]),
                  (FC_BOUNDS[1], FC_BOUNDS[3]),
                  (255, 0, 255), 3)

    cv2.imshow('contours', vis)


def get_n_contours(all_contours, n):
    """
    Get the n largest contours in the set.
    """
    areas = np.array([cv2.contourArea(c) for c in all_contours])

    max_indices = np.argsort(-areas)[:20]
    max_contours = [all_contours[idx] for idx in max_indices]

    print "All Max Contours: {}".format([cv2.contourArea(x) for x in max_contours])
    c_sel = \
        [10000 > cv2.contourArea(c) > 100 for c in max_contours]
        #[10000 > cv2.contourArea(c) > 200 and cv2.isContourConvex(c) for c in max_contours]
    #print "Criteria mask is {}".format(c_sel)
    # print "Area of MAX: %s" % [cv2.contourArea(x) for x in max_contours]

    #meets_criteria = [10000 > cv2.contourArea(x) > 500 for x in max_contours]

    #return max_contours, meets_criteria
    qualifiers = list(compress(max_contours, c_sel))[:n]
    print "Sizes {}, at coords {}".format([cv2.contourArea(x) for x in qualifiers], [get_center(x) for x in qualifiers])

    return qualifiers


def mask_original_frame(frame, coords):
    mask = np.zeros(frame.shape[:2], np.uint8)

    # Coords are L, R, T, B
    cv2.rectangle(mask, (coords[0], coords[2]), (coords[1], coords[3]), 255, -1)
    return cv2.bitwise_and(frame, frame, mask=mask)


def draw_bounding_rect(out_img, contours, filled=2):
    # Filled is 2 by default. If filling is desired, change to -1.

    for c in contours:
        # Now draw bounding box
        x, y, w, h = cv2.boundingRect(c)
        cv2.rectangle(out_img,(x,y),(x+w,y+h),(0,255,0), 2)


def draw_bounding_circle(out_img, contours):

    for c in contours:
        # Or a bounding circle
        (x, y), radius = cv2.minEnclosingCircle(c)
        center = (int(x), int(y))
        radius = int(radius)
        cv2.circle(out_img, center, radius, (0, 0, 255), 5)


def get_center(cnt):

    (x, y), radius = cv2.minEnclosingCircle(cnt)
    x, y = int(x), int(y)
    radius = int(radius)

    return x, y, radius


def find_shortest_distances(curr_cnts, prev_cnts, blues):
    '''Naively assume that for a single coord, shortest distance
    will be a 1-to-1 for all in both curr set and prev set.
    Going to enforce that as a greedy selection.'''
    master_set = []

    curr = [get_center(contour) for contour in curr_cnts]
    prev_coords = [get_center(contour) for contour in prev_cnts]

    print "Looking at curr: {} and prev: {}, with prev_blues: {}".format(curr, prev_coords, blues)
    for x, y, r in curr:
        print "X:%s,Y:%s, prev:%s" % (x, y, prev_coords)
        best_dist = maxint
        best_pair = None
        matched_blue = None
        best_index = None

        for idx, (p_x, p_y, _) in enumerate(prev_coords):
            print "P_x: %s, p_y: %s" % (p_x, p_y)
            dist = sqrt((x - p_x)**2 + (y - p_y)**2)
            print "Dist: %s" % dist
        if dist < best_dist:
            best_dist = dist
            best_pair = p_x, p_y
            matched_blue = blues[idx]
            print "Blue is %s" % matched_blue
            best_index = idx
        # Greedy removal of the lowest distance match for a given point.
        prev_coords.pop(best_index)
        # Associate current x,y to optimal distance pair
        master_set.append([best_pair, (x, y), r, matched_blue])

    return master_set


def determine_alpha_circle(matched_coords):
    '''
    matched_coords- Of the form
        [[(prev_x, prev_y_y), (curr_x, curr_y), curr_radius, is_blue],
         [...], [...]]
    '''

    def extract_prev_x(coord_set):
        return coord_set[0][0]

    def extract_prev_y(coord_set):
        return coord_set[0][1]

    # Gives back min element, then have to extract the x, y values.
    min_prev_x = min(matched_coords, key=extract_prev_x)[0][0]
    min_prev_y = min(matched_coords, key=extract_prev_y)[0][1]

    max_prev_x = max(matched_coords, key=extract_prev_x)[0][0]
    max_prev_y = max(matched_coords, key=extract_prev_y)[0][1]

    for pairings in matched_coords:
        curr_focus_x = pairings[1][0]
        curr_focus_y = pairings[1][1]
        # NOTE: Going to use curr radius to approximate extents of previous
        # contours. Hopefully will be close enough.
        curr_rad = pairings[2]

        print "Min prev: {}, {}, Max prev: {}, {}".format(
            min_prev_x, min_prev_y, max_prev_x, max_prev_y
        )
        print "Radius: {}".format(curr_rad)

        in_x_bounds = \
            min_prev_x - curr_rad < curr_focus_x < max_prev_x + curr_rad
        in_y_bounds = \
            min_prev_y - curr_rad < curr_focus_y < max_prev_y + curr_rad

        if not in_x_bounds and not in_y_bounds:
            # Return just the x, y coords of alpha.
            return pairings[1]


def anticipate_the_future(matched_pairs):

    print "Matched: %s" % matched_pairs
    future_locs = []

    for coord_set in matched_pairs:

        first_x, first_y = coord_set[0]
        sec_x, sec_y = coord_set[1]

        new_x = first_x + 2*(sec_x-first_x)
        new_y = first_y + 2*(sec_y-first_y)

        # Second coords, future coords, radius
        future_locs.append([(sec_x,sec_y), (new_x, new_y), coord_set[2]])

    print "Future %s " % future_locs
    return future_locs


def draw_the_future(out_img, future_pairs):

    print "I want to draw %s " % future_pairs
    for pair in future_pairs:
        cv2.line(out_img, pair[0], pair[1], (0, 0, 255), 3)


if __name__ == '__main__':
    #cProfile.run('main()')
    main()
