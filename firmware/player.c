/* =====================================================================
 *  Аудіопрогравач для DE1-SoC (ARM Cortex-A9) — розширення ЛР5
 * ---------------------------------------------------------------------
 *  Відтворює трек, який застосунок audio_player поклав у пам'ять за
 *  адресою __blob_base (заголовок "DE1A" + блоки IMA ADPCM або PCM16).
 *
 *    KEY0 — пауза / продовження (після кінця треку — заново)
 *    KEY1 — з початку
 *    KEY2 — на 10 с назад,  KEY3 — на 10 с уперед
 *    LEDR9..LEDR0 — шкала рівня гучності з утриманням піку
 *    HEX3..HEX0 — час мм:сс (лише в CPUlator, прапорець у заголовку)
 *
 *  Той самий код працює на платі (система ЛР5, 8 або 48 кГц) і в
 *  CPUlator (8 кГц): частоту, затримку черги звуку й наявність HEX
 *  задає заголовок треку, а не програма.
 * ===================================================================== */

#define LEDR_BASE       0xFF200000u
#define HEX3_HEX0_BASE  0xFF200020u
#define HEX5_HEX4_BASE  0xFF200030u
#define KEY_BASE        0xFF200050u
#define AUDIO_BASE      0xFF203040u     /* +0 Control +4 Fifospace +8 L +C R */
#define TIMER_BASE      0xFFFEC600u     /* приватний таймер A9, 200 МГц     */
#define TIMER_HZ        200000000u

#define MAGIC           0x41314544u     /* "DE1A" */
#define CODEC_PCM16     0
#define CODEC_ADPCM     1
#define FLAG_HEX        0x1u

#define MAX_BLOCK       2048            /* відліків на канал у блоці        */
#define RING            256             /* вікон рівня в кільці (>5 с)      */
#define SEEK_SECONDS    10

typedef unsigned int   u32;
typedef unsigned short u16;
typedef unsigned char  u8;

/* Заголовок треку, 64 байти, порядок байтів ARM */
struct track {
    u32 magic;
    u16 version, codec;
    u32 rate;
    u16 channels, block_samples;
    u32 blocks, block_bytes, total_samples;
    u32 data_off, data_size, checksum;
    u32 flags;
    u32 latency;                        /* затримка черги звуку, відліків   */
    u32 meter_win;                      /* відліків у вікні шкали (20 мс)   */
    u32 max_lag;                        /* наскільки годинник може відстати */
    u32 reserved[2];
};

extern const u8 __blob_base[];          /* задає сценарій компонування      */

static const struct track * T;
static const u8 * data;

/* ------------------------------------------------------------ пристрої */
static volatile u32 * const ledr  = (u32 *)LEDR_BASE;
static volatile u32 * const hex30 = (u32 *)HEX3_HEX0_BASE;
static volatile u32 * const hex54 = (u32 *)HEX5_HEX4_BASE;
static volatile u32 * const key   = (u32 *)KEY_BASE;
static volatile u32 * const audio = (u32 *)AUDIO_BASE;
static volatile u32 * const timer = (u32 *)TIMER_BASE;

static u32 timer_now(void) { return timer[1]; }   /* лічить униз */

static void audio_clear(void) {
    audio[0] = 0xC;                     /* CR, CW: очистити черги */
    audio[0] = 0x0;
}

/* ------------------------------------------------------------ IMA ADPCM */
static const short step_tab[89] = {
        7,     8,     9,    10,    11,    12,    13,    14,    16,    17,
       19,    21,    23,    25,    28,    31,    34,    37,    41,    45,
       50,    55,    60,    66,    73,    80,    88,    97,   107,   118,
      130,   143,   157,   173,   190,   209,   230,   253,   279,   307,
      337,   371,   408,   449,   494,   544,   598,   658,   724,   796,
      876,   963,  1060,  1166,  1282,  1411,  1552,  1707,  1878,  2066,
     2272,  2499,  2749,  3024,  3327,  3660,  4026,  4428,  4871,  5358,
     5894,  6484,  7132,  7845,  8630,  9493, 10442, 11487, 12635, 13899,
    15289, 16818, 18500, 20350, 22385, 24623, 27086, 29794, 32767
};
static const signed char index_tab[16] = {
    -1, -1, -1, -1, 2, 4, 6, 8, -1, -1, -1, -1, 2, 4, 6, 8
};

/* Один канал блоку: 4 байти стану (передбачувач, індекс) + напівбайти */
static void adpcm_decode(const u8 * head, const u8 * nib, int n, short * out) {
    int pred  = (int)(short)(head[0] | (head[1] << 8));
    int index = head[2];
    int i;
    if (index > 88) index = 88;
    for (i = 0; i < n; i++) {
        int code = (i & 1) ? (nib[i >> 1] >> 4) : (nib[i >> 1] & 0xF);
        int step = step_tab[index];
        int diff = step >> 3;
        if (code & 4) diff += step;
        if (code & 2) diff += step >> 1;
        if (code & 1) diff += step >> 2;
        pred = (code & 8) ? pred - diff : pred + diff;
        if (pred > 32767) pred = 32767; else if (pred < -32768) pred = -32768;
        index += index_tab[code];
        if (index < 0) index = 0; else if (index > 88) index = 88;
        out[i] = (short)pred;
    }
}

/* ------------------------------------------------------------ блоки */
static short buf_l[MAX_BLOCK], buf_r[MAX_BLOCK];
static u32 cur_block = 0xFFFFFFFFu;

static void load_block(u32 b) {
    const u8 * p = data + b * T->block_bytes;
    int n = T->block_samples;
    if (T->codec == CODEC_ADPCM) {
        if (T->channels == 2) {
            adpcm_decode(p + 0, p + 8, n, buf_l);
            adpcm_decode(p + 4, p + 8 + n / 2, n, buf_r);
        } else {
            adpcm_decode(p, p + 4, n, buf_l);
        }
    } else {
        const short * s = (const short *)p;
        int i;
        for (i = 0; i < n; i++) buf_l[i] = s[i];
        if (T->channels == 2)
            for (i = 0; i < n; i++) buf_r[i] = s[n + i];
    }
    cur_block = b;
}

/* ------------------------------------------------------------ стан */
enum { PLAYING, PAUSED, ENDED, BROKEN };
static int state;

static u32 pos;             /* наступний відлік, що піде в чергу            */
static u32 blk, off;        /* pos як (блок, зміщення) — без ділення        */
static u32 seek_base;       /* звідки почали після останнього переходу      */
static u32 clk;             /* відлік, який зараз звучить (оцінка)          */
static u32 tick_last;
static unsigned long long tick_acc;

/* рівень гучності: пік модуля за кожне вікно в 20 мс */
static u16 ring[RING];
static u32 win_idx, win_fill;
static u16 win_peak;

static void seek_to(u32 p) {
    if (p > T->total_samples) p = T->total_samples;
    audio_clear();
    pos = seek_base = clk = p;
    blk = p / T->block_samples;
    off = p % T->block_samples;
    win_idx  = p / T->meter_win;
    win_fill = p % T->meter_win;
    win_peak = 0;
    tick_last = timer_now();
    tick_acc = 0;
}

/* Доливає в чергу звуку стільки відліків, скільки туди влізе */
static void fill_fifo(void) {
    u32 space = audio[1];
    u32 wsl = (space >> 24) & 0xFF, wsr = (space >> 16) & 0xFF;
    u32 n = wsl < wsr ? wsl : wsr;

    while (n-- && pos < T->total_samples) {
        short l, r;
        u16 a;
        if (blk != cur_block) load_block(blk);
        l = buf_l[off];
        r = (T->channels == 2) ? buf_r[off] : l;
        audio[2] = (u32)((int)l << 16);
        audio[3] = (u32)((int)r << 16);

        a = (u16)(l < 0 ? -l : l);
        if (a > win_peak) win_peak = a;
        a = (u16)(r < 0 ? -r : r);
        if (a > win_peak) win_peak = a;
        if (++win_fill == T->meter_win) {
            ring[win_idx % RING] = win_peak;
            win_idx++;
            win_fill = 0;
            win_peak = 0;
        }

        pos++;
        if (++off == T->block_samples) { off = 0; blk++; }
    }
}

/* Годинник «що зараз звучить»: іде за таймером, але не випереджає те,
   що вже записано в чергу (мінус її затримка), і не відстає більш ніж
   на max_lag. На платі черга маленька, і годинник просто йде за pos; у
   CPUlator черга спорожнюється блоками по 2048 відліків, і таймер
   згладжує ці стрибки. */
static void update_clock(void) {
    u32 now = timer_now();
    u32 elapsed = tick_last - now;
    u32 hi, lo, n;
    tick_last = now;
    if (state != PLAYING) { tick_acc = 0; return; }

    tick_acc += (unsigned long long)elapsed * T->rate;
    n = (u32)(tick_acc / TIMER_HZ);
    tick_acc -= (unsigned long long)n * TIMER_HZ;
    clk += n;

    hi = (pos >= seek_base + T->latency) ? pos - T->latency : seek_base;
    lo = (hi >= seek_base + T->max_lag) ? hi - T->max_lag : seek_base;
    if (clk > hi) clk = hi;
    if (clk < lo) clk = lo;
}

/* ------------------------------------------------------------ шкала */
/* поріг піку для кожного світлодіода: -39 ... -3 дБ від повної шкали */
static const u16 thr[10] = {
    368, 734, 1305, 2068, 3277, 5193, 8231, 11626, 16423, 23197
};
static int bar, hold, hold_left, fall_left;
static u32 shown_win = 0xFFFFFFFFu;

static int level_of(u16 peak) {
    int k = 0;
    while (k < 10 && peak >= thr[k]) k++;
    return k;
}

static void meter_step(void) {
    u32 w = clk / T->meter_win;
    int lvl = 0;
    /* вікно, у якому зараз годинник, може бути ще не дописане (на платі
       черга коротша за вікно) — тоді беремо останнє завершене */
    if (w >= win_idx) w = win_idx ? win_idx - 1 : 0;
    if (w == shown_win) return;
    shown_win = w;

    if (w * T->meter_win >= seek_base && w < win_idx)
        lvl = level_of(ring[w % RING]);

    if (lvl >= bar) { bar = lvl; fall_left = 2; }        /* миттєвий зліт   */
    else if (--fall_left <= 0) { bar--; fall_left = 2; } /* спад 1 за 40 мс */

    if (lvl >= hold) { hold = lvl; hold_left = 30; }     /* пік — 0,6 с     */
    else if (--hold_left <= 0 && hold > 0) { hold--; hold_left = 3; }
}

static u32 meter_leds(void) {
    u32 v = (1u << bar) - 1u;
    if (hold > 0) v |= 1u << (hold - 1);
    return v;
}

/* ------------------------------------------------------------ HEX */
static const u8 seg7[10] = { 0x3F, 0x06, 0x5B, 0x4F, 0x66, 0x6D, 0x7D, 0x07, 0x7F, 0x6F };

static void show_time(void) {
    u32 s = clk / T->rate, m = s / 60;
    u32 lo = seg7[s % 10] | (seg7[(s % 60) / 10] << 8) |
             ((seg7[m % 10] | 0x80) << 16) | (seg7[(m / 10) % 10] << 24);
    u32 hi = 0;
    if (state == PAUSED) hi = (0x73 << 8) | 0x77;        /* "PA" */
    else if (state == ENDED) hi = (0x79 << 8) | 0x54;    /* "En" */
    *hex30 = lo;
    *hex54 = hi;
}

/* ------------------------------------------------------------ перевірка */
static int track_ok(void) {
    const u32 * w;
    u32 i, n, sum = 0;
    if (T->magic != MAGIC || T->version != 1) return 0;
    if (T->block_samples == 0 || T->block_samples > MAX_BLOCK) return 0;
    if (T->channels < 1 || T->channels > 2 || T->rate == 0 || T->meter_win == 0) return 0;
    w = (const u32 *)data;
    n = (T->data_size + 3) / 4;
    for (i = 0; i < n; i++) sum += w[i];
    return sum == T->checksum;
}

/* ------------------------------------------------------------ головна */
int main(void) {
    u32 k, blink = 0;

    T = (const struct track *)__blob_base;
    data = __blob_base + T->data_off;

    timer[0] = 0xFFFFFFFFu;                 /* Load                       */
    timer[2] = 0x3;                         /* увімкнути, автоперезавантаж */
    key[3] = 0xF;                           /* скинути старі натискання    */
    *ledr = 0;

    if (!track_ok()) {
        state = BROKEN;                     /* треку немає або він битий   */
        for (;;) {
            *ledr = ((timer_now() >> 26) & 1) ? 0x2AA : 0x155;
        }
    }

    seek_to(0);
    state = PLAYING;

    for (;;) {
        k = key[3];                         /* регістр захоплення фронту   */
        if (k) {
            key[3] = k;
            if (k & 0x2) {                  /* KEY1: з початку             */
                seek_to(0);
                state = PLAYING;
            } else if (k & 0x1) {           /* KEY0: пауза / продовження   */
                if (state == PLAYING) { seek_to(clk); state = PAUSED; }
                else if (state == PAUSED) { seek_to(clk); state = PLAYING; }
                else { seek_to(0); state = PLAYING; }
            } else if (k & 0xC) {           /* KEY2 / KEY3: перемотування  */
                u32 d = SEEK_SECONDS * T->rate;
                u32 p = clk;
                if (k & 0x4) p = (p > d) ? p - d : 0;
                else p += d;
                if (p >= T->total_samples) p = T->total_samples;
                if (state == ENDED) state = PLAYING;
                seek_to(p);
            }
            shown_win = 0xFFFFFFFFu;
        }

        if (state == PLAYING) {
            fill_fifo();
            update_clock();
            if (clk >= T->total_samples) { clk = T->total_samples; state = ENDED; }
            meter_step();
            *ledr = meter_leds();
        } else {
            update_clock();
            blink = (timer_now() >> 25) & 1;    /* ~3 Гц                  */
            if (state == PAUSED) *ledr = blink ? meter_leds() : 0;
            else *ledr = 0;
        }
        if (T->flags & FLAG_HEX) show_time();
    }
}
