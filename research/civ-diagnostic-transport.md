# CI-V diagnostic transport map, official v1.42

**Status:** the image links the setting named `CI-V USB Port` to a software
receive path on controller `0xe8007800`, through CI-V framing and the foreground
command dispatcher, then through a queued response to the controller's byte
transmit register. This establishes the software route. It does not identify
the board connector/electrical endpoint or prove a new diagnostic hook safe.
No radio, serial/USB port, or SD card was accessed. The pinned firmware image
was read-only and unchanged during this trace.

## Reproduction

The map is pinned to the official IC-7300 v1.42 container and decoded
application hashes. With Python 3.11, the repository's pinned research
dependencies, and a separately held official v1.42 image, run:

```sh
python3 tools/civ_transport_map.py /path/to/locally-held/7300_142.dat
```

The firmware image is not included in the repository. The verifier checks its
container and decoded-application hashes before reading instruction anchors.

Container SHA-256: `8cf5324a126f105cd2307c30b191b9dd8183f86b2c8bf229e61bf9a6a8c32f32`.
Decoded application SHA-256:
`4686728c9d1f7249b6278a29686a40b8fa5e527bd2428a76a33cd9395178c9a4`.
The verifier checks the configuration descriptors, instruction anchors,
callback tables, and buffer addresses; it only reads the image and prints JSON.

## USB and separate CI-V paths

The settings table names `CI-V Baud Rate` at `0x203de524` (`+0x58`),
`CI-V USB Port` at `0x203de52a` (`+0x5e`), `CI-V USB Baud Rate` at
`0x203de52b` (`+0x5f`), `CI-V USB Echo Back` at `0x203de52c` (`+0x60`), and
`USB Serial Function` at `0x203de52d` (`+0x61`) from config base `0x203de4cc`.
The related menu-group string contains the `CI-V USB` and `REMOTE` labels.

Setup routine `0x20011d38` reads the USB baud, echo-back, and selector fields.
When echo-back is zero it reads `CI-V USB Port`; selector value `6` is mapped
to `1`. When echo-back is nonzero it reads `USB Serial Function` instead. It
stores the selected mode beside the USB frame state and enters controller setup
`0x20011c90`, which loads register base `0xe8007800`.

This is distinct from the separate CI-V serial path at `0xe8007000`, whose
receive callback is registered for event IDs `0xdf`, `0xdd`, and `0xde` and
whose setup reads the general `CI-V Baud Rate` field. The image distinguishes
these software paths and settings. It does not prove that either register block
maps to a particular physical connector, or decode every selector option into
USB-versus-REMOTE hardware behavior.

## Mapped USB receive and response path

```mermaid
flowchart LR
    SET[CI-V USB settings +0x5e/+0x5f] --> INIT[Setup 0x20011d38]
    INIT --> HW[Controller 0xe8007800]
    HW --> RXCB[Events E3/E1/E2 callback 0x20011964]
    RXCB --> BYTE[Read 0xe8007814]
    BYTE --> PARSE[FE/FD parser 0x20011618]
    PARSE --> STATE[Complete frame state 0x20396bc8]
    STATE --> FG[Foreground copy 0x2000b258]
    FG --> DISP[Dispatcher 0x2000b03c]
    DISP --> OUT[Builder buffer 0x20396d20]
    OUT --> Q[USB response state +0x66; pending +0xca]
    Q --> SERVICE[Foreground service 0x20012854]
    SERVICE --> TXBUF[TX staging 0x20396eaf]
    TXBUF --> TXCB[Event E4 callback 0x20011b98]
    TXCB --> WRITE[Byte writer 0x20011968]
    WRITE --> TXREG[Write 0xe800780c]
```

| Stage | Exact-image evidence | What it establishes |
| --- | --- | --- |
| USB setup and callbacks | `0x20011d38` reads config `+0x5e/+0x5f` and selects the `0xe8007800` controller. Events `0xe3`, `0xe1`, and `0xe2` register callback `0x20011964`; event `0xe4` registers `0x20011b98`. | A configured USB-named software transport and its callback entries. The event system's execution context remains unknown. |
| Receive | `0x20011964` branches to `0x2001187c`. That routine reads byte data through `0xe8007814`. Parser `0x20011618` checks `FE` and `FD`, then copies a complete frame from `0x20396e4c` into state at `0x20396bc8`. | USB-configured receive reaches CI-V frame assembly and a state consumed by the command service. |
| Foreground handoff | `0x2000b258` copies a ready frame into dispatcher input `0x20396cbc` and calls `0x2000b03c`. Its call sites include `0x20029b60`; that control-loop path calls USB service `0x20012854` at `0x20029b68`. | Receive parsing and command dispatch are separated by a foreground service call. RTOS task name and scheduling modes are not recovered. |
| Existing response | Dispatcher table `0x2018aa2c` and handler table `0x2018ab84` map command `1a/05` to response callback `0x2000ffb0`. Generic output is built in `0x20396d20`; the builder appends `FD` and sets byte `0x20390034`. For a USB-origin frame, `0x2000b258` copies the response to `0x20396bc8+0x66` and marks `0x20396bc8+0xca` pending. | The existing command reply is carried into the USB state's response queue. `1a/05` itself is not a diagnostic-log command, and this table entry does not certify new-handler safety. |
| USB transmit | With config `+0x60` zero, `0x20012854` moves the queued response into `0x20396eaf`, adds `FE FE`, and copies through `FD`. Event `0xe4` callback `0x20011b98` branches to sender `0x20011a68`, which drains that buffer through byte writer `0x20011968`; the writer stores to `0xe800780c`. | The software response path reaches the configured controller's transmit data register. Board-level USB endpoint wiring is unverified. |

The traced transmit service checks `CI-V USB Echo Back` (`+0x60`). A nonzero
value returns at `0x20012a4c`; this trace does not resolve that alternate
transmit behavior. The configured branch above applies when the field is zero.

## Foreground context, callback split, and buffer ownership

The foreground copy call at `0x20029b60` is in the control loop beginning at
`0x20029914`. That path executes `CPSIE i` at `0x20029b00`, waits at
`0x20029b14`, and branches from `0x20029b5c` into a service loop. The loop
checks state at `0x20029bb0`; when its byte equals 3, `0x20029bb8` branches to
the copy service at `0x20029b60`, followed by USB service at `0x20029b68`.
There is no local `CPSID i` on that selected path. Two other copy-service
callsites are `0x20052f5c` and `0x200531fc`, but their task identities are
unresolved. The event callbacks' execution context is unresolved too; this
evidence does not establish the RTOS task name or every scheduling mode.

The `1a/05` handler row at `0x2018b174` separates three callbacks:

- Row `+4` is input/setting callback `0x2000dcb4`. It parses from dispatcher
  input `0x20396cbc+3` and routes into `0x2000d470` or `0x2000d3f0`. The
  `0x2000d470` path includes a direct store through a descriptor-selected
  pointer at `0x2000d580`.
- Row `+8` is response serializer `0x2000ffb0`.
- Row `+12` is response preflight `0x2000f1c0`.

The normal response route in `0x2000ae28` calls row `+12`, then enters
`0x2000ade0`, which loads and calls row `+8`. It does not call row `+4`. A
future diagnostic callback belongs on that response/serialization side of the
split; reusing the input/setting callback is unsafe. This is structural call
separation, not proof that every helper in a serializer is side-effect free.

The output builder is a shared 100-byte area at `0x20396d20`, marked ready by
the byte at `0x20390034`. `0x2000b258` copies 100 bytes into the selected
transport slot. For the USB route, that is the single observed 100-byte payload
area at `0x20396bc8+0x66`, with a pending marker at `0x20396bc8+0xca`.
`0x20012854` checks transport-state bits and the pending marker before it stages
that response, then clears the marker. This establishes one shared builder and
one observed pending slot; it does not establish FIFO depth or a producer
backpressure guarantee. A diagnostic reader must publish at most one reply at a
time and must establish that the slot is idle before marking the builder ready.

Both the builder-to-queue copy and transmit staging span 100 bytes. The
transmit service prepends two `FE` bytes and scans the queued payload until
`FD`, with no independent length counter in that loop. Thus a conservative
complete response-body limit is 98 bytes including terminal `FD`. Existing
firmware does not enforce this limit: the traced builder appends `FD` without
checking its output cursor, and the USB staging loop has no length guard. A new
handler must enforce the cap before the reply reaches the shared output/queue.
The existing response encoder can expand each byte from `FA` through `FF` to
two encoded bytes, so all payload formulas below count encoded bytes.

## Bounded diagnostic reply sketch (not implemented)

The mapped capacity supports a small fixed status reply and a cursor-based,
whole-record log-read envelope. It does not prove that firmware has a log ring,
what a timing record contains, or what its fixed record size is. This is a
wire-size design sketch only; it assigns no command IDs and adds no handler.

For a future `1a/05`-style response, reserve the worst case: four generic
header bytes, two response command/subcommand bytes, and one `FD`. Under the
98-byte body cap, that leaves at most 91 encoded bytes for the diagnostic
payload. A fixed 16-byte status payload fits. One possible versioned status
layout is:

| Field | Size | Meaning |
| --- | ---: | --- |
| schema version | 1 | Status schema, initially 1 |
| flags | 1 | log available, overflow seen, RTC validity metadata present, firmware cache-latency bound known, native timing qualified |
| fixed record size | 2 | Zero when no log record format is available |
| oldest sequence | 4 | First retained record sequence, or zero when empty |
| next sequence | 4 | Sequence that would be assigned to the next record |
| ring capacity | 2 | Maximum fixed records, or zero when unavailable |
| reserved | 2 | Must be zero |

Do not add a “last sync” field. A reference-validation observation and an
actual RTC sync/set action are different event types and timestamps. Host
reference quality stays in the host log; absent reference-quality evidence or
a firmware cache-latency bound leaves native timing unqualified.

A bounded read request can contain `(first_sequence:u32, max_records:u8)` and
must not accept an address, pointer, or arbitrary memory range. The response
payload can start with a 7-byte header `(schema:u8, first_sequence:u32,
count:u8, more:u8)`, followed by complete fixed-size records only. The
diagnostic payload allowance is 91 encoded bytes; after the 7-byte read header,
84 encoded bytes remain. With worst-case two-byte escaping, a fixed raw record
of `R` bytes permits at most `floor(84 / (2*R))` records per reply. Clamp the
requested count to that value and to the available sequence range; never split
a record. The exact `R`, sequence semantics, and ring layout remain an
implementation gate because no firmware log store was established here.

## Execution context and hook gates

- The receive and transmit callbacks are mapped through event registrations.
  Static evidence does not show whether the event system runs them as an ISR,
  deferred worker, or another context. They access controller registers, poll
  hardware state, and move bytes; do not add a diagnostic ring write or command
  work to those callbacks without further context proof.
- The `0x20029914` loop is the strongest foreground insertion candidate in this
  image. Task identity is still unresolved, and callbacks are not proven to run
  in foreground context.
- The best structural response hook is a distinct row `+8` serializer callback
  reached after row `+12` preflight. There is no safe insertion point until a
  new callback is proven read-only, its encoded output is capped before the
  shared builder is marked ready, and the pending slot's busy/backpressure
  behavior is resolved.
- The traced USB path requires `CI-V USB Echo Back` (`+0x60`) zero. Its nonzero
  branch and selector-to-physical-connector mapping remain unresolved.
- `0xe8007800` and `0xe8007000` are distinct software register paths. The
  `REMOTE` menu label does not prove board-level routing or the actual selected
  value on Arthur's radio.

Focused exact-image regression checks live in
[`tests/test_civ_transport_map.py`](../tests/test_civ_transport_map.py). The
verifier and report are analysis-only; no firmware source was patched or built,
and no hardware interaction occurred in this stage.
