#include "config.h"
#include "io.h"

uint8_t ioBufferRead8(Buffer_t *buf)
{
    return buf->data[buf->index++];
}

uint16_t ioBufferRead16(Buffer_t *buf)
{
    uint16_t result;
    result = buf->data[buf->index++];
    result = (result << (uint16_t)8) | buf->data[buf->index++];
    return result;
}

uint32_t ioBufferRead32(Buffer_t *buf)
{
    uint32_t result;
    result = buf->data[buf->index++];
    result = (result << 8) | buf->data[buf->index++];
    result = (result << 8) | buf->data[buf->index++];
    result = (result << 8) | buf->data[buf->index++];
    return result;
}

void ioBufferWrite8(Buffer_t *buf, uint8_t data)
{
    buf->data[buf->size++] = data;
}

void ioBufferWrite16(Buffer_t *buf, uint16_t data)
{
    buf->data[buf->size++] = (uint8_t)(((data >> (uint16_t)8)) & (uint16_t)0xFF);
    buf->data[buf->size++] = (uint8_t)(data & (uint16_t)0xFF);
}

void ioBufferWrite32(Buffer_t *buf, uint32_t data)
{
    buf->data[buf->size++] = (uint8_t)(((data >> (uint16_t)24)) & (uint16_t)0xFF);
    buf->data[buf->size++] = (uint8_t)(((data >> (uint16_t)16)) & (uint16_t)0xFF);
    buf->data[buf->size++] = (uint8_t)(((data >> (uint16_t)8)) & (uint16_t)0xFF);
    buf->data[buf->size++] = data;
}

uint8_t ioCalculateChecksum(uint8_t *buf, byte size)
{
    uint8_t checksum = 0;
    for (int i = 0; i < size; i++)
    {
        checksum += buf[i];
    }
    return checksum;
}

void ioBufferWriteChecksum(Buffer_t *buf)
{
    uint8_t checksum = ioCalculateChecksum(buf->data, buf->size);
    ioBufferWrite8(buf, checksum);
}
