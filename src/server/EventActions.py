import logging
import json
from RHUtils import catchLogExceptionsWrapper
from eventmanager import Evt

class EventActions:
    eventActionsList = []
    effects = {}

    def __init__(self, eventmanager, RHData):
        self._RHData = RHData
        self.Events = eventmanager
        self.logger = logging.getLogger(self.__class__.__name__)

        self.Events.trigger('actionsInitialize', {
            'registerFn': self.registerEffect
            })

        self.loadActions()
        self.Events.on(Evt.ALL, 'Actions', self.doActions, {}, 200, True)
        self.Events.on(Evt.OPTION_SET, 'Actions', self.loadActions, {}, 200, True)

    def registerEffect(self, effect):
        self.effects[effect.name] = effect
        return True

    def getRegisteredEffects(self):
        return self.effects

    def loadActions(self, _args=None):
        actionSetting = self._RHData.get_option('actions')
        if actionSetting:
            try:
                self.eventActionsList = json.loads(actionSetting)
            except:
                self.logger.error("Can't load stored actions JSON")
        else:
            self.logger.debug("No actions to load")

    def doActions(self, args):
        for action in self.eventActionsList:
            if action['event'] == args['_eventName']:
                self.effects[action['effect']].effectFn(action, args)
                self.logger.debug("Calling effect '{}' with {}".format(action, args))

class ActionEffect():
    def __init__(self, name, label, effectFn, fields):
        self.name = name
        self.label = label
        self.effectFn = effectFn
        self.fields = fields

def initializeEventActions(Events, RHData, RACE, emit_phonetic_text, emit_priority_message, \
                           Language, logger):
    eventActionsObj = None
    try:
        eventActionsObj = EventActions(Events, RHData)

        def getEffectText(action, args, spoken_flag=False):
            text = action['text']
            if '%' in text:
                try:
                    if 'node_index' in args:
                        pilot = RHData.get_pilot(RACE.node_pilots[args['node_index']])
                        pilot_str = pilot.spokenName() if spoken_flag else pilot.callsign
                        text = text.replace('%PILOT%', pilot_str)
                    if 'heat_id' in args:
                        heat = RHData.get_heat(args['heat_id'])
                    else:
                        heat = RHData.get_heat(RACE.current_heat)
                    text = text.replace('%HEAT%', (heat.displayname() if heat else ''))
                    if '%FASTEST' in text:
                        fastest_lap_data = RACE.results.get('meta', {}).get('fastest_lap_data')
                        if fastest_lap_data:
                            logger.debug("Text effect fastest_lap: {} {}".\
                                         format(fastest_lap_data['text'][0], fastest_lap_data['text'][1]))
                            if spoken_flag:
                                fastest_str = "{}, {}".format(fastest_lap_data['phonetic'][0],  # pilot name
                                                              fastest_lap_data['phonetic'][1])  # lap time
                            else:
                                fastest_str = "{} {}".format(fastest_lap_data['text'][0],  # pilot name
                                                             fastest_lap_data['text'][1])  # lap time
                        else:
                            fastest_str = ""
                        # %FASTESTLAP% : Pilot/time for fastest lap in race
                        text = text.replace('%FASTESTLAP%', fastest_str)
                        # %FASTESTLAPCALL% : Pilot/time for fastest lap in race (with prompt)
                        if len(fastest_str) > 0:
                            fastest_str = "{} {}".format(Language.__('Fastest lap'), fastest_str)
                        text = text.replace('%FASTESTLAPCALL%', fastest_str)
                except:
                    logger.exception("Error handling effect text substitution")
            return text

        #register built-in effects

        @catchLogExceptionsWrapper
        def speakEffect(action, args):
            emit_phonetic_text(getEffectText(action, args, spoken_flag=True))

        @catchLogExceptionsWrapper
        def messageEffect(action, args):
            emit_priority_message(getEffectText(action, args))

        @catchLogExceptionsWrapper
        def alertEffect(action, args):
            emit_priority_message(getEffectText(action, args), True)

        eventActionsObj.registerEffect(
            ActionEffect(
                'speak', 
                'Speak',
                speakEffect, 
                [
                    {
                        'id': 'text',
                        'name': 'Callout Text',
                        'type': 'text',
                    }
                ]
            )
        )
        eventActionsObj.registerEffect(
            ActionEffect(
                'message',
                'Message',
                messageEffect,
                [
                    {
                        'id': 'text',
                        'name': 'Message Text',
                        'type': 'text',
                    }
                ]
            )
        )
        eventActionsObj.registerEffect(
            ActionEffect(
                'alert',
                'Alert',
                 alertEffect,
                [
                    {
                        'id': 'text',
                        'name': 'Alert Text',
                        'type': 'text',
                    }
                ]
            )
        )

    except Exception:
        logger.exception("Error loading EventActions")

    return eventActionsObj
