/* cat_world.c - see cat_world.h. Port of pocket_pet/world.py + sim.py. */
#include "cat_world.h"

#include <math.h>
#include <stdio.h>
#include <string.h>

const char *cat_goal_names[CAT_GOALS] = {
    "seek_food", "sleep", "play", "groom", "follow_owner", "scratch", "explore", "hide"
};
const char *cat_drive_names[CAT_DRIVES] = {
    "hunger", "energy", "bored", "clingy", "litter", "curiosity", "bold", "lazy", "scruff", "thirst"
};

/* Anchors in room pixels (the same numbers as world.py). */
typedef struct { const char *name; float x, y; } anchor_t;
static const anchor_t ANCHORS[] = {
    { "food",        54, 128 }, { "water",     104, 152 }, { "toy",   196,  62 },
    { "owner",       60,  74 }, { "litter_box", 286, 146 }, { "window", 160, 26 },
    { "tree",       250,  60 }, { "bed",        86,  44 },
};
#define NEAR_PX 70.0f
#define MID_PX 150.0f
#define SPEED 34.0f           /* room pixels per second */
#define REFLEX_THIRST 6.0f    /* the reflex layer takes over above this */

static const anchor_t *anchor(const char *name) {
    for (size_t i = 0; i < sizeof ANCHORS / sizeof ANCHORS[0]; i++)
        if (!strcmp(ANCHORS[i].name, name)) return &ANCHORS[i];
    return NULL;
}

int cat_goal_index(const char *name) {
    for (int i = 0; i < CAT_GOALS; i++) if (!strcmp(cat_goal_names[i], name)) return i;
    return -1;
}
bool cat_goal_is_reflex(const char *goal) { return goal && !strcmp(goal, "drink"); }

void cat_world_init(cat_state_t *c) {
    memset(c, 0, sizeof *c);
    c->x = 160; c->y = 130; c->heading = 0;
    c->drives[CAT_HUNGER] = 5; c->drives[CAT_ENERGY] = 7; c->drives[CAT_BORED] = 4;
    c->drives[CAT_CLINGY] = 6; c->drives[CAT_LITTER] = 2; c->drives[CAT_CURIOSITY] = 6;
    c->drives[CAT_BOLD] = 5;   c->drives[CAT_LAZY] = 4;   c->drives[CAT_SCRUFF] = 2;
    c->drives[CAT_THIRST] = 2;
    c->goal = "explore"; c->goal_idx = cat_goal_index("explore"); c->last = "explore";
    c->stage = "adult";
    c->tod = "day";
    c->food_left = 3; c->water_left = 3; c->box_clean = true;
    snprintf(c->notice, sizeof c->notice, "ready");
}

static float clamp9(float v) { return v < 0 ? 0 : (v > 9 ? 9 : v); }

/* The model's own 17-field state line, byte-for-byte what State.line() makes. */
void cat_state_line(const cat_state_t *c, char *out, int n) {
    static const char *order[9] = { "hunger", "energy", "bored", "clingy", "litter",
                                    "curiosity", "bold", "lazy", "scruff" };
    int w = snprintf(out, n, "%s %d", order[0], (int)lroundf(c->drives[CAT_HUNGER]));
    for (int i = 1; i < 9; i++) {
        static const int idx[9] = { CAT_HUNGER, CAT_ENERGY, CAT_BORED, CAT_CLINGY, CAT_LITTER,
                                    CAT_CURIOSITY, CAT_BOLD, CAT_LAZY, CAT_SCRUFF };
        w += snprintf(out + w, n - w, " %s %d", order[i], (int)lroundf(c->drives[idx[i]]));
    }
    static const char *where[5] = { "food", "toy", "owner", "litter_box", "window" };
    for (int i = 0; i < 5; i++) {
        const anchor_t *a = anchor(where[i]);
        float dx = a->x - c->x, dy = a->y - c->y;
        float d = sqrtf(dx * dx + dy * dy);
        if (d > MID_PX) {
            w += snprintf(out + w, n - w, " %s far", where[i]);
        } else {
            float ang = atan2f(dx, -dy) * 180.0f / (float)M_PI;
            int clock = (int)((ang + 360.0f) / 30.0f) % 12 + 1;
            w += snprintf(out + w, n - w, " %s %s %d", where[i],
                          d <= NEAR_PX ? "near" : "mid", clock);
        }
    }
    snprintf(out + w, n - w, " stage %s last %s time %s", c->stage, c->last, c->tod ? c->tod : "day");
}

void cat_goal_target(const cat_state_t *c, float *tx, float *ty) {
    const char *name = NULL;
    if (cat_goal_is_reflex(c->goal))           name = "water";
    else if (!strcmp(c->goal, "seek_food"))    name = "food";
    else if (!strcmp(c->goal, "play"))         name = "toy";
    else if (!strcmp(c->goal, "scratch"))      name = "tree";
    else if (!strcmp(c->goal, "sleep"))        name = "bed";
    else if (!strcmp(c->goal, "follow_owner")) name = "owner";
    if (name) { const anchor_t *a = anchor(name); *tx = a->x; *ty = a->y; return; }
    /* explore / hide: drift somewhere in the room, deterministically per frame */
    *tx = 30.0f + (float)((c->frame / 37) % 26) * 10.0f;
    *ty = 50.0f + (float)((c->frame / 53) % 12) * 10.0f;
}

void cat_world_set_goal(cat_state_t *c, const char *goal) {
    if (!goal) return;
    if (cat_goal_is_reflex(goal)) { c->goal = goal; c->goal_idx = -1; }
    else { int i = cat_goal_index(goal); if (i < 0) return; c->goal = cat_goal_names[i]; c->goal_idx = i; }
    c->asleep = !strcmp(goal, "sleep");
}

static void arrive(cat_state_t *c) {
    float *d = c->drives;
    if (!strcmp(c->goal, "seek_food")) {
        if (c->food_left > 0) {
            c->food_left -= 1;
            d[CAT_HUNGER] = clamp9(d[CAT_HUNGER] - 4);
            d[CAT_ENERGY] = clamp9(d[CAT_ENERGY] + 1);
            snprintf(c->notice, sizeof c->notice, "eating (%d left)", (int)c->food_left);
        } else {
            snprintf(c->notice, sizeof c->notice, "the bowl is empty");
        }
    } else if (!strcmp(c->goal, "drink")) {
        if (c->water_left > 0) {
            c->water_left -= 1;
            d[CAT_THIRST] = clamp9(d[CAT_THIRST] - 5);
            snprintf(c->notice, sizeof c->notice, "drinking (%d left)", (int)c->water_left);
        } else {
            snprintf(c->notice, sizeof c->notice, "the water bowl is empty");
        }
    } else if (!strcmp(c->goal, "sleep")) {
        d[CAT_ENERGY] = clamp9(d[CAT_ENERGY] + 3);
        snprintf(c->notice, sizeof c->notice, "purring in its sleep");
    } else if (!strcmp(c->goal, "play")) {
        d[CAT_BORED] = clamp9(d[CAT_BORED] - 3);
        d[CAT_ENERGY] = clamp9(d[CAT_ENERGY] - 1);
        snprintf(c->notice, sizeof c->notice, "pouncing");
    } else if (!strcmp(c->goal, "groom")) {
        d[CAT_SCRUFF] = clamp9(d[CAT_SCRUFF] - 4);
        snprintf(c->notice, sizeof c->notice, "grooming");
    } else if (!strcmp(c->goal, "scratch")) {
        d[CAT_LITTER] = clamp9(d[CAT_LITTER] - 5);
        c->box_clean = true;
        snprintf(c->notice, sizeof c->notice, "using the litter box");
    } else if (!strcmp(c->goal, "follow_owner")) {
        d[CAT_CLINGY] = clamp9(d[CAT_CLINGY] - 2);
        snprintf(c->notice, sizeof c->notice, "rubbing against you");
    } else {
        snprintf(c->notice, sizeof c->notice, "wandering");
    }
    c->last = c->goal;
}

void cat_world_tick(cat_state_t *c, float dt) {
    float *d = c->drives;
    c->frame++;
    /* the world moves on (rates are per second; a sim minute is a cat-hour) */
    d[CAT_HUNGER] = clamp9(d[CAT_HUNGER] + 0.10f * dt);
    d[CAT_BORED]  = clamp9(d[CAT_BORED] + (c->asleep ? 0.04f : 0.22f) * dt);
    if (c->asleep) d[CAT_ENERGY] = clamp9(d[CAT_ENERGY] + 0.55f * dt);
    else           d[CAT_ENERGY] = clamp9(d[CAT_ENERGY] - 0.14f * dt);
    d[CAT_LITTER]  = clamp9(d[CAT_LITTER] + 0.05f * dt);
    d[CAT_SCRUFF]  = clamp9(d[CAT_SCRUFF] + 0.06f * dt);
    d[CAT_CLINGY]  = clamp9(d[CAT_CLINGY] + 0.09f * dt);
    d[CAT_THIRST]  = clamp9(d[CAT_THIRST] + 0.12f * dt);
    if (!c->box_clean) d[CAT_LITTER] = clamp9(d[CAT_LITTER] + 0.10f * dt);

    /* the reflex layer: thirst outranks whatever the model wanted - unless the
     * bowl is empty and the cat has already waited, in which case it stands down
     * for a while (otherwise a dry bowl freezes the cat at the water bowl) */
    if (c->snooze_frames > 0) c->snooze_frames--;
    if (d[CAT_THIRST] >= REFLEX_THIRST && c->snooze_frames == 0 && strcmp(c->goal, "drink") != 0) {
        cat_world_set_goal(c, "drink");
        snprintf(c->notice, sizeof c->notice, "thirsty - going to the water bowl");
    }
    if (!strcmp(c->goal, "drink")) {
        if (c->water_left > 0) { c->blocked_frames = 0; }
        else if (++c->blocked_frames > 200) {                  /* ~10 s at 20 fps */
            c->blocked_frames = 0;
            c->snooze_frames = 3000;                           /* ~2.5 min */
            snprintf(c->notice, sizeof c->notice, "the bowl is dry - giving up for now");
            cat_world_set_goal(c, "explore");
        }
    } else {
        c->blocked_frames = 0;
    }

    float tx, ty;
    cat_goal_target(c, &tx, &ty);
    float dx = tx - c->x, dy = ty - c->y;
    float dist = sqrtf(dx * dx + dy * dy);
    if (dist < 5.0f) {
        c->moving = false;
        arrive(c);
        return;
    }
    c->moving = c->asleep ? false : true;
    if (c->asleep) return;
    c->heading = atan2f(dx, -dy) * 180.0f / (float)M_PI;
    if (c->heading < 0) c->heading += 360.0f;
    float step = SPEED * dt;
    if (step > dist) step = dist;
    c->x += dx / dist * step;
    c->y += dy / dist * step;
    c->walking = (c->walking + 1) % 3;
}

void cat_feed(cat_state_t *c) {
    c->food_left = 3;
    c->drives[CAT_HUNGER] = clamp9(c->drives[CAT_HUNGER] + 1);   /* it smells the food */
    snprintf(c->notice, sizeof c->notice, "food bowl filled");
}
void cat_water(cat_state_t *c) {
    c->water_left = 3;
    c->drives[CAT_THIRST] = clamp9(c->drives[CAT_THIRST] + 2);
    snprintf(c->notice, sizeof c->notice, "water bowl filled");
}
void cat_play_with(cat_state_t *c) {
    c->drives[CAT_BORED] = clamp9(c->drives[CAT_BORED] + 3);
    c->drives[CAT_CURIOSITY] = clamp9(c->drives[CAT_CURIOSITY] + 1);
    snprintf(c->notice, sizeof c->notice, "you wave the toy - the cat is interested");
}
void cat_pet(cat_state_t *c) {
    c->drives[CAT_SCRUFF] = clamp9(c->drives[CAT_SCRUFF] - 3);
    c->drives[CAT_CLINGY] = clamp9(c->drives[CAT_CLINGY] + 1);
    c->drives[CAT_BOLD] = clamp9(c->drives[CAT_BOLD] + 1);
    snprintf(c->notice, sizeof c->notice, "purr");
}
void cat_clean_box(cat_state_t *c) {
    c->drives[CAT_LITTER] = 0;
    c->box_clean = true;
    snprintf(c->notice, sizeof c->notice, "litter box cleaned");
}
