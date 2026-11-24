/* chirp_frames_tx.c — B-side multi-frame LoRa transmitter for the minigame drill.
 *
 * Sends a SEQUENCE of pre-sealed 245B frames (frame_00.bin, frame_01.bin, ...)
 * inside ONE lgw_start session, so a 14-frame burst does not pay the
 * probabilistic-start tax 14 times (skill law: "Concentrator starts are
 * PROBABILISTIC" — one certified start, N sends).
 *
 * HAL API: sx1302_hal v2.1.0 (lgw_txgain_setconf / lgw_status TX_STATUS).
 * RF params default to the fleet-proven M1 line: 903.9 MHz, SF9, BW 125 kHz,
 * 14 dBm, RF chain 0, SX1250 single-input, pwr_idx 12 (--pa 1 --pwid 12).
 *
 * Build (from libloragw/):
 *   gcc -O2 -Wall -Wextra -std=c99 -Iinc -I. -I../libtools/inc \
 *       <this file> libloragw.a ../libtools/libtinymt32.a -o chirp_frames_tx -lrt -lm
 *
 * Run from the libloragw/ directory (HAL tools invoke ./reset_lgw.sh by
 * RELATIVE path via system()).
 *
 * Evidence contract:
 *   CHIRP_TX_FRAME_<idx>_BYTES=<n>
 *   CHIRP_TX_FRAME_<idx>_REPS=<r>_STATUS=TX_DONE|TX_ERROR(code=<c>)
 *   CHIRP_TX_COMPLETE=YES (every scheduled send reached TX_FINISHED)
 */
#define _DEFAULT_SOURCE
#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <unistd.h>
#include <getopt.h>
#include <dirent.h>
#include "loragw_hal.h"

#define SPI_DEV_DEFAULT "/dev/spidev0.0"
#define MAX_FRAME 255

static void usage(void) {
    printf("chirp_frames_tx — multi-frame LoRa transmitter (sx1302_hal v2.1.0)\n");
    printf("  -d <dir>    directory with frame_00.bin, frame_01.bin, ... (required)\n");
    printf("  -f <float>  TX frequency MHz (default 903.9)\n");
    printf("  -s <uint>   SF (default 9)\n");
    printf("  -b <uint>   BW kHz (default 125)\n");
    printf("  -p <int>    power dBm (default 14)\n");
    printf("  -n <uint>   reps per frame (default 1)\n");
    printf("  -g <uint>   gap seconds between frames (default 2)\n");
    printf("  -c <path>   SPI device (default %s)\n", SPI_DEV_DEFAULT);
}

static int frame_index_cmp(const void *a, const void *b) {
    return (*(const int *)a) - (*(const int *)b);
}

int main(int argc, char **argv) {
    const char *com_path = SPI_DEV_DEFAULT;
    const char *dir_path = NULL;
    double freq_mhz = 903.9;
    unsigned sf = 9, bw_khz = 125, nb_send = 1, gap_s = 2;
    int rf_power = 14;
    int opt;

    while ((opt = getopt(argc, argv, "f:s:b:p:n:g:c:d:h")) != -1) {
        switch (opt) {
            case 'f': freq_mhz = atof(optarg); break;
            case 's': sf = atoi(optarg); break;
            case 'b': bw_khz = atoi(optarg); break;
            case 'p': rf_power = atoi(optarg); break;
            case 'n': nb_send = atoi(optarg); break;
            case 'g': gap_s = atoi(optarg); break;
            case 'c': com_path = optarg; break;
            case 'd': dir_path = optarg; break;
            default: usage(); return (opt == 'h') ? 0 : 1;
        }
    }
    if (!dir_path) { fprintf(stderr, "ERROR: -d <frames dir> required\n"); usage(); return 1; }
    if (nb_send == 0) nb_send = 1;

    /* Collect frame files: frame_<idx>.bin, index parsed from the name */
    DIR *d = opendir(dir_path);
    if (!d) { perror("opendir"); return 1; }
    int idxs[512]; int nframes = 0;
    struct dirent *de;
    while ((de = readdir(d)) != NULL) {
        if (strncmp(de->d_name, "frame_", 6) != 0) continue;
        if (!strstr(de->d_name, ".bin")) continue;
        int i = atoi(de->d_name + 6);
        if (i >= 0 && i < 512 && nframes < 512) idxs[nframes++] = i;
    }
    closedir(d);
    if (nframes == 0) { fprintf(stderr, "ERROR: no frame_*.bin in %s\n", dir_path); return 1; }
    qsort(idxs, nframes, sizeof(int), frame_index_cmp);

    printf("chirp_frames_tx: dir=%s frames=%u freq=%.1fMHz SF%u BW%ukHz %ddBm reps=%u gap=%us\n",
           dir_path, nframes, freq_mhz, sf, bw_khz, rf_power, nb_send, gap_s);

    /* Board + radio configuration — mirrors the fleet-proven B-side TX line */
    struct lgw_conf_board_s board;
    memset(&board, 0, sizeof board);
    board.lorawan_public = true;
    board.clksrc = 0;
    board.com_type = LGW_COM_SPI;
    snprintf(board.com_path, sizeof board.com_path, "%s", com_path);

    struct lgw_conf_rxrf_s rfconf;
    memset(&rfconf, 0, sizeof rfconf);
    rfconf.enable = true;
    rfconf.freq_hz = (uint32_t)(freq_mhz * 1e6);
    rfconf.tx_enable = true;
    rfconf.type = LGW_RADIO_TYPE_SX1250;
    rfconf.single_input_mode = true; /* -j equivalent */

    struct lgw_conf_rxrf_s rfconf2;
    memset(&rfconf2, 0, sizeof rfconf2);
    rfconf2.enable = false;

    struct lgw_tx_gain_lut_s txlut;
    memset(&txlut, 0, sizeof txlut);
    txlut.size = 1;
    txlut.lut[0].rf_power = (int8_t)rf_power;
    txlut.lut[0].pa_gain = 1;
    txlut.lut[0].mix_gain = 5; /* HAL validates mix_gain [5..15] even for SX1250 */
    txlut.lut[0].pwr_idx = 12; /* --pwid 12 of the proven B-side TX command line */

    if (lgw_board_setconf(&board) != LGW_HAL_SUCCESS) { fprintf(stderr, "ERROR: board_setconf\n"); return 1; }
    if (lgw_rxrf_setconf(0, &rfconf) != LGW_HAL_SUCCESS) { fprintf(stderr, "ERROR: rxrf_setconf(0)\n"); return 1; }
    if (lgw_rxrf_setconf(1, &rfconf2) != LGW_HAL_SUCCESS) { fprintf(stderr, "ERROR: rxrf_setconf(1)\n"); return 1; }
    if (lgw_txgain_setconf(0, &txlut) != LGW_HAL_SUCCESS) { fprintf(stderr, "ERROR: txgain_setconf\n"); return 1; }

    /* Board reset immediately before lgw_start (GPIO17 pulse via reset_lgw.sh) */
    if (system("./reset_lgw.sh start") != 0) {
        fprintf(stderr, "ERROR: failed to reset SX1302 (reset_lgw.sh start)\n");
        return 1;
    }
    if (lgw_start() != LGW_HAL_SUCCESS) { fprintf(stderr, "ERROR: lgw_start\n"); return 1; }

    struct lgw_pkt_tx_s pkt;
    memset(&pkt, 0, sizeof pkt);
    pkt.freq_hz = (uint32_t)(freq_mhz * 1e6);
    pkt.tx_mode = IMMEDIATE;
    pkt.rf_chain = 0;
    pkt.rf_power = (int8_t)rf_power;
    pkt.modulation = MOD_LORA;
    pkt.bandwidth = BW_125KHZ;
    pkt.datarate = sf;
    pkt.coderate = 1;  /* CR 4/5 */
    pkt.preamble = 8;
    pkt.invert_pol = false;

    unsigned total_ok = 0, total_sched = 0, frames_ok = 0;
    unsigned nframes_u = (unsigned)nframes;

    for (int fi = 0; fi < nframes; fi++) {
        char path[1024];
        snprintf(path, sizeof path, "%s/frame_%02d.bin", dir_path, idxs[fi]);
        FILE *fp = fopen(path, "rb");
        if (!fp) { perror(path); continue; }
        uint8_t frame[MAX_FRAME];
        size_t n = fread(frame, 1, MAX_FRAME, fp);
        int ferr = ferror(fp);
        fclose(fp);
        if (ferr || n == 0) { fprintf(stderr, "ERROR: reading %s\n", path); continue; }

        pkt.size = n;
        memcpy(pkt.payload, frame, n);
        printf("CHIRP_TX_FRAME_%d_BYTES=%zu\n", idxs[fi], n);

        unsigned frame_ok = 0;
        for (unsigned r = 0; r < nb_send; r++) {
            int rc = lgw_send(&pkt);
            total_sched++;
            if (rc != LGW_HAL_SUCCESS) {
                printf("CHIRP_TX_FRAME_%d_REPS=%u_STATUS=SEND_FAIL\n", idxs[fi], r + 1);
                continue;
            }
            uint8_t code = TX_STATUS_UNKNOWN;
            int spins = 0;
            do {
                usleep(5000);
                rc = lgw_status(0, TX_STATUS, &code);
                spins++;
            } while (rc == LGW_HAL_SUCCESS && code != TX_FREE && spins < 4000);
            if (rc == LGW_HAL_SUCCESS && code == TX_FREE) {
                frame_ok++; total_ok++;
                printf("CHIRP_TX_FRAME_%d_REPS=%u_STATUS=TX_DONE\n", idxs[fi], r + 1);
            } else {
                printf("CHIRP_TX_FRAME_%d_REPS=%u_STATUS=TX_ERROR(code=%u)\n", idxs[fi], r + 1, code);
            }
            usleep(1000000); /* 1 s between reps */
        }
        if (frame_ok == nb_send) frames_ok++;
        if (fi + 1 < nframes) sleep(gap_s);
    }

    lgw_stop();
    printf("CHIRP_TX_FRAMES=%u/%u_OK CHIRP_TX_SENDS=%u/%u_OK\n",
           frames_ok, nframes_u, total_ok, total_sched);
    if (frames_ok == nframes_u && total_ok == total_sched) {
        printf("CHIRP_TX_COMPLETE=YES\n");
        return 0;
    }
    printf("CHIRP_TX_COMPLETE=NO\n");
    return 1;
}
