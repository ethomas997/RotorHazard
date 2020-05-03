#include "config.h"
#include "rhtypes.h"
#include "RssiNode.h"
#include "commands.h"

#ifdef __TEST__
  static uint8_t i2cSlaveAddress = 0x08;
#else
#if !STM32_MODE_FLAG
  extern uint8_t i2cSlaveAddress;
#else
  void doJumpToBootloader();
#endif
#endif

void handleReadLapPassStats(Message_t *msg, mtime_t timeNowVal);
void handleReadLapExtremums(Message_t *msg, mtime_t timeNowVal);

uint8_t settingChangedFlags = 0;

RssiNode *cmdRssiNodePtr = &(RssiNode::rssiNodeArray[0]);  //current RssiNode for commands

RssiNode *getCmdRssiNodePtr()
{
    return cmdRssiNodePtr;
}

byte getPayloadSize(uint8_t command)
{
    byte size;
    switch (command)
    {
        case WRITE_FREQUENCY:
            size = 2;
            break;

        case WRITE_ENTER_AT_LEVEL:  // lap pass begins when RSSI is at or above this level
            size = 1;
            break;

        case WRITE_EXIT_AT_LEVEL:  // lap pass ends when RSSI goes below this level
            size = 1;
            break;

        case FORCE_END_CROSSING:  // kill current crossing flag regardless of RSSI value
            size = 1;
            break;

        case RESET_PAIRED_NODE:  // reset paired node for ISP
            size = 1;
            break;

        case WRITE_CURNODE_INDEX:  // index of current node for this processor
            size = 1;
            break;

        case JUMP_TO_BOOTLOADER:  // jump to bootloader for flash update
            size = 1;
            break;

        default:  // invalid command
            LOG_ERROR("Invalid write command: ", command, HEX);
            size = -1;
    }
    return size;
}

// Node reset for ISP; resets other node wired to this node's reset pin
void resetPairedNode(int pinState)
{
    if (pinState)
    {
        pinMode(NODE_RESET_PIN, INPUT_PULLUP);
    }
    else
    {
        pinMode(NODE_RESET_PIN, OUTPUT);
        digitalWrite(NODE_RESET_PIN, LOW);
    }
}

// Generic IO write command handler
void handleWriteCommand(Message_t *msg, bool serialFlag)
{
    uint8_t u8val;
    uint16_t u16val;
    rssi_t rssiVal;
    uint8_t nIdx;

    msg->buffer.index = 0;
    bool actFlag = true;

    switch (msg->command)
    {
        case WRITE_FREQUENCY:
            u16val = ioBufferRead16(&(msg->buffer));
            if (u16val >= MIN_FREQ && u16val <= MAX_FREQ)
            {
                if (u16val != cmdRssiNodePtr->getVtxFreq())
                {
                    cmdRssiNodePtr->setVtxFreq(u16val);
                    settingChangedFlags |= FREQ_CHANGED;
#if STM32_MODE_FLAG
                    cmdRssiNodePtr->rssiStateReset();  // restart rssi peak tracking for node
#endif
                }
                settingChangedFlags |= FREQ_SET;
#if STM32_MODE_FLAG  // need to wait here for completion to avoid data overruns
                cmdRssiNodePtr->setRxModuleToFreq(u16val);
                cmdRssiNodePtr->setActivatedFlag(true);
#endif
            }
            break;

        case WRITE_ENTER_AT_LEVEL:  // lap pass begins when RSSI is at or above this level
            rssiVal = ioBufferReadRssi(&(msg->buffer));
            if (rssiVal != cmdRssiNodePtr->getEnterAtLevel())
            {
                cmdRssiNodePtr->setEnterAtLevel(rssiVal);
                settingChangedFlags |= ENTERAT_CHANGED;
            }
            break;

        case WRITE_EXIT_AT_LEVEL:  // lap pass ends when RSSI goes below this level
            rssiVal = ioBufferReadRssi(&(msg->buffer));
            if (rssiVal != cmdRssiNodePtr->getExitAtLevel())
            {
                cmdRssiNodePtr->setExitAtLevel(rssiVal);
                settingChangedFlags |= EXITAT_CHANGED;
            }
            break;

        case WRITE_CURNODE_INDEX:  // index of current node for this processor
            nIdx = ioBufferRead8(&(msg->buffer));
            if (nIdx < RssiNode::multiRssiNodeCount && nIdx != cmdRssiNodePtr->getNodeIndex())
                cmdRssiNodePtr = &(RssiNode::rssiNodeArray[nIdx]);
            break;

        case FORCE_END_CROSSING:  // kill current crossing flag regardless of RSSI value
            cmdRssiNodePtr->rssiEndCrossing();
            break;

        case RESET_PAIRED_NODE:  // reset paired node for ISP
            u8val = ioBufferRead8(&(msg->buffer));
            resetPairedNode(u8val);
            break;

        case JUMP_TO_BOOTLOADER:  // jump to bootloader for flash update
#if STM32_MODE_FLAG
            doJumpToBootloader();
#endif
            break;

        default:
            LOG_ERROR("Invalid write command: ", msg->command, HEX);
            actFlag = false;  // not valid activity
    }

    // indicate communications activity detected
    if (actFlag)
    {
        settingChangedFlags |= COMM_ACTIVITY;
        if (serialFlag)
            settingChangedFlags |= SERIAL_CMD_MSG;
    }

    msg->command = 0;  // Clear previous command
}

void ioBufferWriteExtremum(Buffer_t *buf, Extremum *e, mtime_t now)
{
    ioBufferWriteRssi(buf, e->rssi);
    ioBufferWrite16(buf, uint16_t(now - e->firstTime));
    ioBufferWrite16(buf, uint16_t(now - e->firstTime - e->duration));
}

// Generic IO read command handler
void handleReadCommand(Message_t *msg, bool serialFlag)
{
    msg->buffer.size = 0;
    bool actFlag = true;

    switch (msg->command)
    {
        case READ_ADDRESS:
#if !STM32_MODE_FLAG
            ioBufferWrite8(&(msg->buffer), i2cSlaveAddress);
#else
            ioBufferWrite8(&(msg->buffer), (uint8_t)0);
#endif
            break;

        case READ_FREQUENCY:
            ioBufferWrite16(&(msg->buffer), cmdRssiNodePtr->getVtxFreq());
            break;

        case READ_LAP_STATS:  // deprecated; use READ_LAP_PASS_STATS and READ_LAP_EXTREMUMS
            {
                mtime_t timeNowVal = millis();
                handleReadLapPassStats(msg, timeNowVal);
                handleReadLapExtremums(msg, timeNowVal);
                settingChangedFlags |= LAPSTATS_READ;
            }
            break;

        case READ_LAP_PASS_STATS:
            handleReadLapPassStats(msg, millis());
            settingChangedFlags |= LAPSTATS_READ;
            break;

        case READ_LAP_EXTREMUMS:
            handleReadLapExtremums(msg, millis());
            break;

        case READ_ENTER_AT_LEVEL:  // lap pass begins when RSSI is at or above this level
            ioBufferWriteRssi(&(msg->buffer), cmdRssiNodePtr->getEnterAtLevel());
            break;

        case READ_EXIT_AT_LEVEL:  // lap pass ends when RSSI goes below this level
            ioBufferWriteRssi(&(msg->buffer), cmdRssiNodePtr->getExitAtLevel());
            break;

        case READ_REVISION_CODE:  // reply with NODE_API_LEVEL and verification value
            ioBufferWrite16(&(msg->buffer), (0x25 << 8) + NODE_API_LEVEL);
            break;

        case READ_NODE_RSSI_PEAK:
            ioBufferWriteRssi(&(msg->buffer), cmdRssiNodePtr->getState().nodeRssiPeak);
            break;

        case READ_NODE_RSSI_NADIR:
            ioBufferWriteRssi(&(msg->buffer), cmdRssiNodePtr->getState().nodeRssiNadir);
            break;

        case READ_TIME_MILLIS:
            ioBufferWrite32(&(msg->buffer), millis());
            break;

        case READ_RHFEAT_FLAGS:   // reply with feature flags value
            ioBufferWrite16(&(msg->buffer), RHFEAT_FLAGS_VALUE);
            break;

        case READ_MULTINODE_COUNT:
            ioBufferWrite8(&(msg->buffer), RssiNode::multiRssiNodeCount);
            break;

        case READ_CURNODE_INDEX:
            ioBufferWrite8(&(msg->buffer), cmdRssiNodePtr->getNodeIndex());
            break;

        default:  // If an invalid command is sent, write nothing back, master must react
            LOG_ERROR("Invalid read command: ", msg->command, HEX);
            actFlag = false;  // not valid activity
    }

    // indicate communications activity detected
    if (actFlag)
    {
        settingChangedFlags |= COMM_ACTIVITY;
        if (serialFlag)
            settingChangedFlags |= SERIAL_CMD_MSG;
    }

    if (msg->buffer.size > 0)
    {
        ioBufferWriteChecksum(&(msg->buffer));
    }

    msg->command = 0;  // Clear previous command
}

void handleReadLapPassStats(Message_t *msg, mtime_t timeNowVal)
{
    ioBufferWrite8(&(msg->buffer), cmdRssiNodePtr->getLastPass().lap);
    ioBufferWrite16(&(msg->buffer), uint16_t(timeNowVal - cmdRssiNodePtr->getLastPass().timestamp));  // ms since lap
    ioBufferWriteRssi(&(msg->buffer), cmdRssiNodePtr->getState().rssi);
    ioBufferWriteRssi(&(msg->buffer), cmdRssiNodePtr->getState().nodeRssiPeak);
    ioBufferWriteRssi(&(msg->buffer), cmdRssiNodePtr->getLastPass().rssiPeak);  // RSSI peak for last lap pass
    ioBufferWrite16(&(msg->buffer), uint16_t(cmdRssiNodePtr->getState().loopTimeMicros));
}

void handleReadLapExtremums(Message_t *msg, mtime_t timeNowVal)
{
    // set flag if 'crossing' in progress
    uint8_t flags = cmdRssiNodePtr->getState().crossing ?
            (uint8_t)LAPSTATS_FLAG_CROSSING : (uint8_t)0;
    if (isPeakValid(cmdRssiNodePtr->getHistory().peakSend) &&
            (!isNadirValid(cmdRssiNodePtr->getHistory().nadirSend)
            || (cmdRssiNodePtr->getHistory().peakSend.firstTime <
                    cmdRssiNodePtr->getHistory().nadirSend.firstTime)))
    {
        flags |= LAPSTATS_FLAG_PEAK;
    }
    ioBufferWrite8(&(msg->buffer), flags);
    ioBufferWriteRssi(&(msg->buffer), cmdRssiNodePtr->getLastPass().rssiNadir);  // lowest rssi since end of last pass
    ioBufferWriteRssi(&(msg->buffer), cmdRssiNodePtr->getState().nodeRssiNadir);

    if ((flags & (uint8_t)LAPSTATS_FLAG_PEAK) != (uint8_t)0)
    {
        // send peak and reset
        ioBufferWriteExtremum(&(msg->buffer), &(cmdRssiNodePtr->getHistory().peakSend), timeNowVal);
        cmdRssiNodePtr->getHistory().peakSend.rssi = 0;
    }
    else if (isNadirValid(cmdRssiNodePtr->getHistory().nadirSend)
          && (!isPeakValid(cmdRssiNodePtr->getHistory().peakSend)
            || (cmdRssiNodePtr->getHistory().nadirSend.firstTime <
                    cmdRssiNodePtr->getHistory().peakSend.firstTime)))
    {
        // send nadir and reset
        ioBufferWriteExtremum(&(msg->buffer), &(cmdRssiNodePtr->getHistory().nadirSend), timeNowVal);
        cmdRssiNodePtr->getHistory().nadirSend.rssi = MAX_RSSI;
    }
    else
    {
        ioBufferWriteRssi(&(msg->buffer), 0);
        ioBufferWrite16(&(msg->buffer), 0);
        ioBufferWrite16(&(msg->buffer), 0);
    }
}
