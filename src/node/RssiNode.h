#ifndef RSSINODE_H_
#define RSSINODE_H_

#include "config.h"
#include "rhtypes.h"
#include "FastRunningMedian.h"

#define MAX_RSSI 0xFF
#define MAX_DURATION 0xFFFF
#define SmoothingSamples 255
#define SmoothingTimestampSize 128 // half median window, rounded up
#define isPeakValid(x) ((x).rssi != 0)
#define isNadirValid(x) ((x).rssi != MAX_RSSI)
#define endTime(x) ((x).firstTime + (x).duration)

#define RX5808_MIN_TUNETIME 35  // after set freq need to wait this long before read RSSI
#define RX5808_MIN_BUSTIME 30   // after set freq need to wait this long before setting again

struct Settings
{
    uint16_t volatile vtxFreq = 5800;
    // lap pass begins when RSSI is at or above this level
    rssi_t volatile enterAtLevel = 96;
    // lap pass ends when RSSI goes below this level
    rssi_t volatile exitAtLevel = 80;
};

struct Extremum
{
  rssi_t volatile rssi;
  mtime_t volatile firstTime;
  uint16_t volatile duration;
};

struct State
{
    bool volatile crossing = false; // True when the quad is going through the gate
    rssi_t volatile rssi = 0; // Smoothed rssi value
    rssi_t lastRssi = 0;
    mtime_t rssiTimestamp = 0; // timestamp of the smoothed value

    Extremum passPeak = {0, 0, 0}; // peak seen during current pass - only valid if pass.rssi != 0
    rssi_t passRssiNadir = MAX_RSSI; // lowest smoothed rssi seen since end of last pass

    rssi_t volatile nodeRssiPeak = 0; // peak smoothed rssi seen since the node frequency was set
    rssi_t volatile nodeRssiNadir = MAX_RSSI; // lowest smoothed rssi seen since the node frequency was set

    bool volatile activatedFlag = false; // Set true after initial WRITE_FREQUENCY command received

    // variables to track the loop time
    utime_t volatile loopTimeMicros = 0;
    utime_t lastloopMicros = 0;
};

struct History
{
    Extremum peak = {0, 0, 0};
    bool volatile hasPendingPeak = false;
    Extremum peakSend = {0, 0, 0}; // only valid if peakSend.rssi != 0

    Extremum nadir = {MAX_RSSI, 0, 0};
    bool volatile hasPendingNadir = false;
    Extremum nadirSend = {MAX_RSSI, 0, 0}; // only valid if nadirSend.rssi != MAX_RSSI

    int8_t rssiChange = 0; // >0 for raising, <0 for falling
};

struct LastPass
{
    rssi_t volatile rssiPeak = 0;
    mtime_t volatile timestamp = 0;
    rssi_t volatile rssiNadir = MAX_RSSI;
    uint8_t volatile lap = 0;
};


class RssiNode
{
    uint8_t nodeIndex = 0;       //node index (0 if first or only node)

    uint16_t rx5808DataPin = 0;  //DATA (CH1) output line to RX5808 module
    uint16_t rx5808ClkPin = 0;   //CLK (CH3) output line to RX5808 module
    uint16_t rx5808SelPin = 0;   //SEL (CH2) output line to RX5808 module
    uint16_t rssiInputPin = 0;   //RSSI input from RX5808

    struct Settings settings;
    struct State state;
    struct History history;
    struct LastPass lastPass;
    FastRunningMedian<rssi_t, SmoothingSamples, 0> rssiMedian;
    mtime_t SmoothingTimestamps[SmoothingTimestampSize];
    uint8_t SmoothingTimestampsIndex = 0;

    bool rxPoweredDown = false;
    bool recentSetFreqFlag = false;
    mtime_t lastSetFreqTimeMs = 0;
    static mtime_t lastRX5808BusTimeMs;

    void rx5808SerialSendBit1();
    void rx5808SerialSendBit0();
    void rx5808SerialEnableLow();
    void rx5808SerialEnableHigh();

    void setRxModulePower(uint32_t options);
    void resetRxModule();
    void setupRxModule();
    void powerDownRxModule();

    rssi_t rssiRead();
    void bufferHistoricPeak(bool force);
    void bufferHistoricNadir(bool force);
    void initExtremum(Extremum *e);

    static uint16_t freqMhzToRegVal(uint16_t freqInMhz);
#if STM32_MODE_FLAG
    static int rx5808SelPinForNodeIndex(int nIdx);
    static int rssiInputPinForNodeIndex(int nIdx);
#endif

public:
    static RssiNode rssiNodeArray[MULTI_RHNODE_MAX];
    static uint8_t multiRssiNodeCount;

    RssiNode();
    void initRx5808Pins(int nIdx);
    void initRxModule();
    void setRxModuleToFreq(uint16_t vtxFreq);

    void rssiInit();
    bool rssiStateValid();
    void rssiStateReset();  //restarts rssi peak tracking for node
    bool rssiProcess(mtime_t millis);
    void rssiEndCrossing();

    uint8_t getNodeIndex() { return nodeIndex; }
    bool getActivatedFlag() { return state.activatedFlag; }
    void setActivatedFlag(bool flgVal) { state.activatedFlag = flgVal; }
    uint16_t getVtxFreq() { return settings.vtxFreq; }
    void setVtxFreq(uint16_t freqVal) { settings.vtxFreq = freqVal; }
    rssi_t getEnterAtLevel() { return settings.enterAtLevel; }
    void setEnterAtLevel(rssi_t val) { settings.enterAtLevel = val; }
    rssi_t getExitAtLevel() { return settings.exitAtLevel; }
    void setExitAtLevel(rssi_t val) { settings.exitAtLevel = val; }

    struct State & getState() { return state; }
    struct History & getHistory() { return history; }
    struct LastPass & getLastPass()  { return lastPass; }
};

#endif  //RSSINODE_H_
