#ifndef IC7300_ALLOC_H
#define IC7300_ALLOC_H
#include <stddef.h>
void *tracked_malloc(size_t);
void *tracked_calloc(size_t,size_t);
void tracked_free(void *);
size_t tracked_peak(void);
size_t tracked_live(void);
#endif
