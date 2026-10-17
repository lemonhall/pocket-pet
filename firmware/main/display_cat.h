/* display_cat.h - the Tab5's glass, and the room drawn on it. */
#pragma once

#include "cat_world.h"

/* Brings the BSP up (I2C, LCD power, DSI, backlight). False = no picture. */
bool display_cat_init(void);
/* Draws the room, the cat and the status bars into a fresh frame buffer. */
void display_cat_frame(const cat_state_t *c);
/* Backlight 0..100. */
void display_cat_brightness(int pct);
/* Draw a short-lived marker where a tap landed (landscape view coordinates).
 * It makes the touch mapping checkable by eye: the dot must sit under your finger. */
void display_cat_mark(int vx, int vy);
int  display_cat_fps(void);
