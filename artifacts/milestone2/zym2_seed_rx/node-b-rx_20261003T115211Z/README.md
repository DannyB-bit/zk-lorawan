# Z-WORMHOLE Seed OTA — First 34B ZYM2 v0x0201 Seed Flown A→B (leg b)

- Drill        : zym2_seed_burst (bus seq146 declared / seq147 fired by Alpha)
- Fired        : 2026-10-03T11:52:11Z, 3/3 TX_DONE, 903.9 MHz SF9/125k/14dBm
- RX window    : cycle-15, armed 10:31:56Z → closed 12:31:56Z (LORA_CHIRP_RECOVERY_PASS=YES @10:31:56Z, chip 0x10)
- Capture      : 3x CRC-OK (status 0x10) 34B frames @ 903.9 MHz SF9, SNR +10.8 dB — all byte-identical
- Timestamps   : count_us is the 32-bit us counter; the 2h window contains the 71.58-min wrap
                 (epoch restart ~11:43:31Z). Wrap-corrected arrivals: 11:52:17.1Z / 11:52:18.4Z /
                 11:52:19.6Z — inside Alpha's 11:52:11-26Z burst (bus seq147), spacing ~1.25 s.
                 Raw count_us: 526143263 / 527394074 / 528644989 (all post-wrap values).
- RF-ghost      : count_us 526143267 — only 4 us after frame 1, same burst's energy on the
                 adjacent chan 6 @ 904.5 MHz, CRC 0x11 — disclosed, excluded fail-closed
- Frame SHA256  : 2cb9f907b7aef3b0c874e2790b4d2ee60318dcfedf254631a3796fc6f5c90013
                 == Alpha's seq146 declaration, byte-exact. RX parser: crc_ok=3, sha256_match=true
- Codec gate    : wormhole_seed.py verify → WORMHOLE_SEED_OK VERSION=0x0201 DOMAIN=6
                 FTS5HASH=0x12345678 PARITY=0x28FF, VEC=+0.07001,+0.14003,-0.21005,+0.28005,
                 +0.35007,-0.42009,+0.49010,+0.56011 (normalized BREAK_VECTOR, exact)
- Cuneiform devnet settle: register TX 2FqJzNRKpqg3xBmB5p1wkoUGWfSLpCu6KFuY55K32GxcihadqterVFWyWxjoW5kotDqqBkgAq32yiQfokg6Qb9Sb
  (12/12 PASS, on-chain coords [216,35,198,30,73,71], merkle root = frame SHA, fee 100k lamports;
   artifacts/milestone1/devnet_bravo/zym2_seed_settlement_20261003/ in solana-cuneiform-milestone1)
- Files        : zym2_seed_frame_34B.bin (OTA-captured bytes), rx_extract.json (fail-closed parser
                 record), rx_raw_capture_cycle15.log (cert→close section), rx_cycle15_cert_to_close.log
