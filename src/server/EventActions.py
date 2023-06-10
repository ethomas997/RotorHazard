import logging
import json
from RHUtils import catchLogExceptionsWrapper
from eventmanager import Evt

class EventActions:
    eventActionsList = []
    effects = {}

    def __init__(self, eventmanager, RaceContext):
        self._racecontext = RaceContext
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
        actionSetting = self._racecontext.rhdata.get_option('actions')
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
                args['results'] = self._racecontext.race.get_results()
                self.effects[action['effect']].runAction(action, args)
                self.logger.debug("Calling effect '{}' with {}".format(action, args))

class ActionEffect():
    def __init__(self, name, label, effectFn, fields):
        self.name = name
        self.label = label
        self.effectFn = effectFn
        self.fields = fields

    @catchLogExceptionsWrapper
    def runAction(self, action, args):
        self.effectFn(action, args)

