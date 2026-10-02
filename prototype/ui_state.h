#ifndef IC7300_UI_STATE_H
#define IC7300_UI_STATE_H
#include "station.h"

typedef enum {
    FT8_UI_ACTION_ENABLE,
    FT8_UI_ACTION_CANCEL
} ft8_ui_action;

/* Volatile host-prototype state. No settings or storage representation exists. */
typedef struct {
    bool initialized;
    bool enabled;
} ft8_ui_state;

/* Starts disabled. Call before dispatching actions; boot never enables QSO. */
bool ft8_ui_state_init(ft8_ui_state *);

/* Cancels the current station session, then leaves the UI state disabled. */
bool ft8_ui_state_reset(ft8_ui_state *, ft8_station *);

/* The future UI adapter may dispatch only explicit enable/cancel actions here.
 * Enable requires an initialized QSO and a caller-configured time policy. */
bool ft8_ui_dispatch(ft8_ui_state *, ft8_station *, ft8_ui_action);

#endif
