''' builtin Actions '''

from EventActions import ActionEffect

class ActionsBuiltin():
    def __init__(self, RHAPI):
        self._RHAPI = RHAPI

    def doReplace(self, text, args, spoken_flag=False):
        if '%' in text:
            # %HEAT%
            if 'heat_id' in args:
                heat = self._RHAPI.get_heat(args['heat_id'])
            else:
                heat = self._RHAPI.get_heat(self._RHAPI.race_heat)
    
            text = text.replace('%HEAT%', heat.displayname())
    
            if 'results' in args:
                race_results = args['results']
                if 'node_index' in args:
                    lboard_name = race_results.get('meta', {}).get('primary_leaderboard', '')
                    leaderboard = race_results.get(lboard_name, [])

                    for result in leaderboard:
                        if result['node'] == args['node_index']:
                            # %LAP_COUNT%
                            text = text.replace('%LAP_COUNT%', str(result['laps']))

                            # %TOTAL_TIME%
                            text = text.replace('%TOTAL_TIME%', result['total_time'])

                            # %TOTAL_TIME_LAPS%
                            text = text.replace('%TOTAL_TIME_LAPS%', result['total_time_laps'])

                            # %LAST_LAP%
                            text = text.replace('%LAST_LAP%', result['last_lap'])

                            # %AVERAGE_LAP%
                            text = text.replace('%AVERAGE_LAP%', result['average_lap'])

                            # %FASTEST_LAP%
                            text = text.replace('%FASTEST_LAP%', result['fastest_lap'])

                            # %CONSECUTIVE%
                            if result['consecutives_base'] == int(self._RHAPI.get_setting('consecutivesCount', 3)):
                                text = text.replace('%CONSECUTIVE%', result['consecutives'])
                            else:
                                text = text.replace('%CONSECUTIVE%', __('None'))

                            # %POSITION%
                            text = text.replace('%POSITION%', str(result['position']))

                            break

                if '%FASTEST_RACE_LAP' in text:
                    fastest_race_lap_data = race_results.get('meta', {}).get('fastest_race_lap_data')
                    if fastest_race_lap_data:
                        if spoken_flag:
                            fastest_str = "{}, {}".format(fastest_race_lap_data['phonetic'][0],  # pilot name
                                                          fastest_race_lap_data['phonetic'][1])  # lap time
                        else:
                            fastest_str = "{} {}".format(fastest_race_lap_data['text'][0],  # pilot name
                                                         fastest_race_lap_data['text'][1])  # lap time
                    else:
                        fastest_str = ""
                    # %FASTESTLAP% : Pilot/time for fastest lap in race
                    text = text.replace('%FASTEST_RACE_LAP%', fastest_str)
                    # %FASTESTLAPCALL% : Pilot/time for fastest lap in race (with prompt)
                    if len(fastest_str) > 0:
                        fastest_str = "{} {}".format(__('Fastest lap'), fastest_str)
                    text = text.replace('%FASTEST_RACE_LAP_CALL%', fastest_str)

        return text

    def speakEffect(self, action, args):
        if 'text' in action:
            text = self.doReplace(action['text'], args, True)

            # %PILOT%
            if 'node_index' in args:
                pilot = self._RHAPI.get_pilot(self._RHAPI.race_pilots[args['node_index']])
                text = text.replace('%PILOT%', pilot.spokenName())

            self._RHAPI.emit_phonetic_text(text)

    def messageEffect(self, action, args):
        if 'text' in action:
            text = self.doReplace(action['text'], args)

            # %PILOT%
            if 'node_index' in args:
                pilot = self._RHAPI.get_pilot(self._RHAPI.race_pilots[args['node_index']])
                text = text.replace('%PILOT%', pilot.displayCallsign())

            self._RHAPI.emit_priority_message(text)

    def alertEffect(self, action, args):
        if 'text' in action:
            text = self.doReplace(action['text'], args)

            # %PILOT%
            if 'node_index' in args:
                pilot = self._RHAPI.get_pilot(self._RHAPI.race_pilots[args['node_index']])
                text = text.replace('%PILOT%', pilot.displayCallsign())

            self._RHAPI.emit_priority_message(text, True)

    def scheduleEffect(self, action, args):
        if 'sec' in action:
            if 'min' in action:
                self._RHAPI.race_schedule(action['sec'], action['min'])
            else:
                self._RHAPI.race_schedule(action['sec'])

actions = None

def initialize(**kwargs):
    if 'Events' in kwargs:
        kwargs['Events'].on('actionsInitialize', 'action_builtin', registerHandlers, {}, 75)
    if '__' in kwargs:
        __ = kwargs['__']

    global actions
    actions = ActionsBuiltin(kwargs['RHAPI'])

def registerHandlers(args):
    if 'registerFn' in args:
        for effect in discover():
            args['registerFn'](effect)

def discover():
    return [
        ActionEffect(
            'speak',
            'Speak',
            actions.speakEffect,
            [
                {
                    'id': 'text',
                    'name': 'Callout Text',
                    'type': 'text',
                }
            ]
        ),
        ActionEffect(
            'message',
            'Message',
            actions.messageEffect,
            [
                {
                    'id': 'text',
                    'name': 'Message Text',
                    'type': 'text',
                }
            ]
        ),
        ActionEffect(
            'alert',
            'Alert',
            actions.alertEffect,
            [
                {
                    'id': 'text',
                    'name': 'Alert Text',
                    'type': 'text',
                }
            ]
        ),
        ActionEffect(
            'schedule',
            'Schedule Race',
            actions.scheduleEffect,
            [
                {
                    'id': 'sec',
                    'name': 'Seconds',
                    'type': 'basic_int',
                },
                {
                    'id': 'min',
                    'name': 'Minutes',
                    'type': 'basic_int',
                }
            ]
        )
    ]

def __(arg): # Replaced with outer language.__ during initialize()
    return arg