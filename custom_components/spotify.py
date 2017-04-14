"""
Support for interacting with Spotify Connect.

For more details about this platform, please refer to the documentation at
https://home-assistant.io/components/media_player.spotify/
"""

import logging
from datetime import timedelta

import voluptuous as vol

from homeassistant.core import callback
from homeassistant.loader import get_component
from homeassistant.components.http import HomeAssistantView
from homeassistant.components.media_player import (
    MEDIA_TYPE_MUSIC, MEDIA_TYPE_PLAYLIST, SUPPORT_VOLUME_SET,
    SUPPORT_PLAY, SUPPORT_PAUSE, SUPPORT_PLAY_MEDIA, SUPPORT_NEXT_TRACK,
    SUPPORT_PREVIOUS_TRACK, SUPPORT_SELECT_SOURCE, PLATFORM_SCHEMA,
    MediaPlayerDevice)
from homeassistant.const import (
    CONF_NAME, STATE_PLAYING, STATE_PAUSED, STATE_IDLE, STATE_UNKNOWN)
import homeassistant.helpers.config_validation as cv


COMMIT = '544614f4b1d508201d363e84e871f86c90aa26b2'
REQUIREMENTS = ['https://github.com/happyleavesaoc/spotipy/'
                'archive/%s.zip#spotipy==2.4.4' % COMMIT]

DEPENDENCIES = ['http']

_LOGGER = logging.getLogger(__name__)

SUPPORT_SPOTIFY = SUPPORT_VOLUME_SET | SUPPORT_PAUSE | SUPPORT_PLAY |\
    SUPPORT_NEXT_TRACK | SUPPORT_PREVIOUS_TRACK | SUPPORT_SELECT_SOURCE |\
    SUPPORT_PLAY_MEDIA

SCOPE = 'user-read-playback-state user-modify-playback-state'
DEFAULT_CACHE_PATH = '.spotify-token-cache'
AUTH_CALLBACK_PATH = '/api/spotify'
AUTH_CALLBACK_NAME = 'api:spotify'
ICON = 'mdi:spotify'
DEFAULT_NAME = 'Spotify'
DOMAIN = 'spotify'
CONF_CLIENT_ID = 'client_id'
CONF_CLIENT_SECRET = 'client_secret'
CONF_CACHE_PATH = 'cache_path'
CONFIGURATOR_LINK_NAME = 'Link Spotify account'
CONFIGURATOR_SUBMIT_CAPTION = 'I authorized successfully'
CONFIGURATOR_DESCRIPTION = 'To link your Spotify account, ' \
                           'click the link, login, and authorize:'

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_CLIENT_ID): cv.string,
    vol.Required(CONF_CLIENT_SECRET): cv.string,
    vol.Optional(CONF_NAME): cv.string,
    vol.Optional(CONF_CACHE_PATH): cv.string
})

SCAN_INTERVAL = timedelta(seconds=30)


def request_configuration(hass, config, add_devices, oauth):
    """Request Spotify authorization."""
    configurator = get_component('configurator')
    hass.data[DOMAIN] = configurator.request_config(
        hass, DEFAULT_NAME, lambda _: None,
        link_name=CONFIGURATOR_LINK_NAME,
        link_url=oauth.get_authorize_url(),
        description=CONFIGURATOR_DESCRIPTION,
        submit_caption=CONFIGURATOR_SUBMIT_CAPTION)


def setup_platform(hass, config, add_devices, discovery_info=None):
    """Setup the Spotify platform."""
    import spotipy.oauth2
    callback_url = '{}{}'.format(hass.config.api.base_url, AUTH_CALLBACK_PATH)
    cache = config.get(CONF_CACHE_PATH, hass.config.path(DEFAULT_CACHE_PATH))
    oauth = spotipy.oauth2.SpotifyOAuth(
        config.get(CONF_CLIENT_ID), config.get(CONF_CLIENT_SECRET),
        callback_url, scope=SCOPE,
        cache_path=cache)
    token_info = oauth.get_cached_token()
    if not token_info:
        _LOGGER.info('no token; requesting authorization')
        hass.http.register_view(SpotifyAuthCallbackView(
            config, add_devices, oauth))
        request_configuration(hass, config, add_devices, oauth)
        return
    if hass.data.get(DOMAIN):
        configurator = get_component('configurator')
        configurator.request_done(hass.data.get(DOMAIN))
        del hass.data[DOMAIN]
    player = SpotifyMediaPlayer(oauth, config.get(CONF_NAME, DEFAULT_NAME))
    add_devices([player], True)


class SpotifyAuthCallbackView(HomeAssistantView):
    """Spotify Authorization Callback View."""

    requires_auth = False
    url = AUTH_CALLBACK_PATH
    name = AUTH_CALLBACK_NAME

    def __init__(self, config, add_devices, oauth):
        """Initialize."""
        self.config = config
        self.add_devices = add_devices
        self.oauth = oauth

    @callback
    def get(self, request):
        """Receive authorization token."""
        hass = request.app['hass']
        self.oauth.get_access_token(request.GET['code'])
        hass.async_add_job(setup_platform, hass, self.config, self.add_devices)


class SpotifyMediaPlayer(MediaPlayerDevice):
    """Representation of a Spotify controller."""

    def __init__(self, oauth, name):
        """Initialize."""
        self._name = name
        self._oauth = oauth
        self._album = None
        self._title = None
        self._artist = None
        self._uri = None
        self._image_url = None
        self._state = STATE_UNKNOWN
        self._current_device = None
        self._devices = None
        self._volume = None
        self._player = None
        self._token_info = self._oauth.get_cached_token()

    def refresh_spotify_instance(self):
        """Fetch a new spotify instance."""
        import spotipy
        token_refreshed = False
        need_token = (self._token_info is None or
                      self._oauth.is_token_expired(self._token_info))
        if need_token:
            new_token = \
                self._oauth.refresh_access_token(
                    self._token_info['refresh_token'])
            self._token_info = new_token
            token_refreshed = True
        if self._player is None or token_refreshed:
            self._player = \
                spotipy.Spotify(auth=self._token_info.get('access_token'))

    def update(self):
        """Update state and attributes."""
        self.refresh_spotify_instance()
        current = self._player.current_playback()
        if current is None:
            self._state = STATE_IDLE
            return
        # Track metadata
        item = current.get('item')
        if item:
            self._album = item.get('album').get('name')
            self._title = item.get('name')
            self._artist = ', '.join([artist.get('name')
                                      for artist in item.get('artists')])
            self._uri = current.get('uri')
            self._image_url = item.get('album').get('images')[0].get('url')
        # Playing state
        self._state = STATE_PAUSED
        if current.get('is_playing'):
            self._state = STATE_PLAYING
        device = current.get('device')
        if device is None:
            self._state = STATE_IDLE
        else:
            if device.get('volume_percent'):
                self._volume = device.get('volume_percent') / 100
            if device.get('name'):
                self._current_device = device.get('name')
        # Available devices
        self._devices = {device.get('name'): device.get('id')
                         for device in self._player.devices().get('devices')}

    def set_volume_level(self, volume):
        """Set the volume level."""
        self._player.volume(int(volume * 100))
        self.schedule_update_ha_state()

    def media_next_track(self):
        """Skip to next track."""
        self._player.next_track()
        self.schedule_update_ha_state()

    def media_previous_track(self):
        """Skip to previous track."""
        self._player.previous_track()
        self.schedule_update_ha_state()

    def media_play(self):
        """Start or resume playback."""
        self._player.start_playback()
        self.schedule_update_ha_state()

    def media_pause(self):
        """Pause playback."""
        self._player.pause_playback()
        self.schedule_update_ha_state()

    def select_source(self, source):
        """Select playback device."""
        self._player.transfer_playback(self._devices[source])
        self.schedule_update_ha_state()

    def play_media(self, media_type, media_id, **kwargs):
        """Play media."""
        kwargs = {}
        if media_type == MEDIA_TYPE_MUSIC:
            kwargs['uris'] = [media_id]
        elif media_type == MEDIA_TYPE_PLAYLIST:
            kwargs['context_uri'] = media_id
        else:
            _LOGGER.error('media type %s is not supported', media_type)
            return
        if not media_id.startswith('spotify:'):
            _LOGGER.error('media id must be spotify uri')
            return
        self._player.start_playback(**kwargs)
        self.schedule_update_ha_state()

    @property
    def name(self):
        """Name."""
        return self._name

    @property
    def icon(self):
        """Icon."""
        return ICON

    @property
    def state(self):
        """Playback state."""
        return self._state

    @property
    def volume_level(self):
        """Device volume."""
        return self._volume

    @property
    def source_list(self):
        """Playback devices."""
        return list(self._devices.keys())

    @property
    def source(self):
        """Current playback device."""
        return self._current_device

    @property
    def media_content_id(self):
        """Media URL."""
        return self._uri

    @property
    def media_image_url(self):
        """Media image url."""
        return self._image_url

    @property
    def media_artist(self):
        """Media artist."""
        return self._artist

    @property
    def media_album_name(self):
        """Media album."""
        return self._album

    @property
    def media_title(self):
        """Media title."""
        return self._title

    @property
    def supported_features(self):
        """Media player features that are supported."""
        return SUPPORT_SPOTIFY
