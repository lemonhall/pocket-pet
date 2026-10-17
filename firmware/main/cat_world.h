/* cat_world.h - the cat's drives, its goals, and the things you can do to it.
 *
 * Port of pocket_pet/{world,sim}.py, with one deliberate difference: `thirst` is
 * a REFLEX-LAYER-ONLY drive. The model's state line (17 fields) does not contain
 * it, so `drink` is not one of the eight goals the model chooses from - when the
 * cat is thirsty the reflex layer overrides the model and sends it to the water
 * bowl. That is the reflex/advisor split ECN-0001 settled on, not a shortcut:
 * adding a field to the schema would invalidate the 50k labels and the model.
 */
#pragma once

#include <stdbool.h>
#include <stdint.h>

#define CAT_DRIVES 10          /* the 9 in the model's state line + thirst */
#define CAT_GOALS  8           /* what the model picks from */
#define CAT_TARGETS 8

/* Drives, in the order the status bar and the state line use. */
enum {
    CAT_HUNGER, CAT_ENERGY, CAT_BORED, CAT_CLINGY, CAT_LITTER,
    CAT_CURIOSITY, CAT_BOLD, CAT_LAZY, CAT_SCRUFF, CAT_THIRST
};

/* The nine goals: eight are the model's, `drink` is the reflex layer's. */
extern const char *cat_goal_names[CAT_GOALS];
extern const char *cat_drive_names[CAT_DRIVES];

typedef struct {
    float x, y;                 /* room pixels, 0..320 / 0..180 */
    float heading;              /* degrees, 0 = up */
    bool moving, asleep;
    int walking;                /* sprite frame cycle */
    float drives[CAT_DRIVES];
    int goal_idx;               /* index into cat_goal_names, -1 = reflex goal */
    const char *goal;           /* the goal as text (may be "drink") */
    const char *last;           /* what it did before */
    const char *stage;
    const char *tod;            /* dawn|day|dusk|night, set from the RTC by main */
    int frame;                  /* frames since boot, for animation */
    /* larder: how much food and water is in the bowls (you refill them) */
    float food_left, water_left;
    bool box_clean;
    /* reflex bookkeeping: a cat does not stand at an empty bowl for ever. If the
     * reflex goal cannot satisfy its drive, it stands down for a while and lets
     * the model drive again - otherwise thirst outranks hunger indefinitely. */
    int blocked_frames, snooze_frames;
    /* visible feedback timers: a tap must produce something you can SEE, not just
     * a changed number (the user's complaint, 2026-10-17) */
    int purr_frames;            /* >0: stop, face the camera, show a heart */
    int toy_wiggle;             /* >0: the toy is being waved */
    int spot;                   /* increments on every arrival: pick a new random
                                 * wander target only then, never per frame (a
                                 * per-frame target made the cat jitter left-right) */
    /* A tap is a summons: for a while the model may not overrule the goal you
     * pointed at, so clicking the tree really does bring the cat over to it. */
    int summon_frames;
    /* what just happened, for the status line */
    char notice[48];
} cat_state_t;

void  cat_world_init(cat_state_t *c);
void  cat_world_tick(cat_state_t *c, float dt);      /* drift + move + act */
void  cat_world_set_goal(cat_state_t *c, const char *goal);
/* Interactions - each one changes a drive and leaves a notice. */
void  cat_feed(cat_state_t *c);
void  cat_water(cat_state_t *c);
void  cat_play_with(cat_state_t *c);
void  cat_pet(cat_state_t *c);
void  cat_clean_box(cat_state_t *c);
/* The state line the model reads, exactly 17 fields. */
void  cat_state_line(const cat_state_t *c, char *out, int n);
/* Summons: the goal you tapped wins for ~30 s (repeatable by tapping again). */
void  cat_world_summon(cat_state_t *c, const char *goal);
bool  cat_world_summoned(const cat_state_t *c);
/* Where the cat should walk for its current goal (room pixels). */
void  cat_goal_target(const cat_state_t *c, float *tx, float *ty);
int   cat_goal_index(const char *name);
bool  cat_goal_is_reflex(const char *goal);
