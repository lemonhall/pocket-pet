/* pet_state.h - pocket-pet v1: the ONE source of truth for the cat's state line
 * and its goals.
 *
 * Both sides read THIS file: the firmware (C) and the Python tooling
 * (pocket_pet/header.py). `pocket_pet.check_schema` enforces that the header and
 * docs/pet/*.md agree, so a field can never be added in one place only.
 *
 * Field kinds: NUM = 0..span-1 integer; WHERE = none | near|mid|far <clock 1..12>;
 * META = stage (kitten|adult|elder) / last (a goal) / time (dawn|day|dusk|night).
 * See docs/prd/PRD-0001-pocket-pet-cat.md REQ-0001-001. */

#define PET_FIELD_LIST \
    PET_FIELD(hunger,     NUM,   10) \
    PET_FIELD(energy,     NUM,   10) \
    PET_FIELD(bored,      NUM,   10) \
    PET_FIELD(clingy,     NUM,   10) \
    PET_FIELD(litter,     NUM,   10) \
    PET_FIELD(curiosity,  NUM,   10) \
    PET_FIELD(bold,       NUM,   10) \
    PET_FIELD(lazy,       NUM,   10) \
    PET_FIELD(scruff,     NUM,   10) \
    PET_FIELD(food,       WHERE,  0) \
    PET_FIELD(toy,        WHERE,  0) \
    PET_FIELD(owner,      WHERE,  0) \
    PET_FIELD(litter_box, WHERE,  0) \
    PET_FIELD(window,     WHERE,  0) \
    PET_FIELD(stage,      META,   0) \
    PET_FIELD(last,       META,   0) \
    PET_FIELD(time,       META,   0)

/* The eight goals. Order matters: the token ids the model learns follow this. */
#define PET_GOAL_LIST \
    PET_GOAL(seek_food) \
    PET_GOAL(sleep) \
    PET_GOAL(play) \
    PET_GOAL(groom) \
    PET_GOAL(follow_owner) \
    PET_GOAL(scratch) \
    PET_GOAL(explore) \
    PET_GOAL(hide)

/* ---- C side ---- */

#define PET_FIELD_ENUM(name, kind, span) PET_F_##name,
typedef enum { PET_FIELD_LIST PET_F_COUNT } pet_field_t;
#undef PET_FIELD_ENUM

#define PET_GOAL_ENUM(name) PET_G_##name,
typedef enum { PET_GOAL_LIST PET_G_COUNT } pet_goal_t;
#undef PET_GOAL_ENUM

#define PET_STAGE_LIST(X) X(kitten) X(adult) X(elder)
#define PET_TIME_LIST(X)  X(dawn) X(day) X(dusk) X(night)
