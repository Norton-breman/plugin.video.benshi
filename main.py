# Copyright (C) 2023, Roman V. M.
# Copyright (C) 2026, Norton-breman (plugin.video.benshi)
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""
Plugin vidéo Benshi pour Kodi 20.x « Nexus » et supérieur.

Authentification via les paramètres de l'addon, puis navigation dans le
catalogue (sélections, tous les films, recherche). La lecture sera ajoutée
à l'étape suivante.
"""
import os
import sys
from urllib.parse import parse_qsl, urlencode

import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs

URL = sys.argv[0]
HANDLE = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].lstrip('-').isdigit() else -1

ADDON = xbmcaddon.Addon()
ADDON_PATH = xbmcvfs.translatePath(ADDON.getAddonInfo('path'))
PROFILE_PATH = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))
ICON = ADDON.getAddonInfo('icon')

sys.path.insert(0, os.path.join(ADDON_PATH, 'resources', 'lib'))
import api        # noqa: E402
import storage    # noqa: E402

PAGE_SIZE = 30


# --------------------------------------------------------------------- Outils

def get_url(**kwargs):
    """Construit une URL d'appel récursif du plugin."""
    return '{}?{}'.format(URL, urlencode(kwargs))


def get_api():
    store = storage.FileTokenStore(os.path.join(PROFILE_PATH, 'token_cache.json'))
    return api.BenshiApi(token_store=store)


def get_credentials():
    return ADDON.getSetting('email').strip(), ADDON.getSetting('password')


def notify(message, heading='Benshi', icon=xbmcgui.NOTIFICATION_INFO, time_ms=5000):
    xbmcgui.Dialog().notification(heading, message, icon, time_ms)


# ------------------------------------------------------------ Authentification

def login():
    """Valide l'accès au compte. Renvoie un AuthResult ou None (et prévient)."""
    email, password = get_credentials()
    if not email or not password:
        notify("Renseignez vos identifiants Benshi dans les paramètres.",
               icon=xbmcgui.NOTIFICATION_WARNING)
        ADDON.openSettings()
        return None
    try:
        return get_api().authenticate(email, password)
    except api.BenshiAuthError as exc:
        notify(str(exc), icon=xbmcgui.NOTIFICATION_ERROR)
    except api.BenshiNetworkError:
        notify("Connexion au serveur impossible. Vérifiez votre réseau.",
               icon=xbmcgui.NOTIFICATION_ERROR)
    except api.BenshiError as exc:
        notify(str(exc), icon=xbmcgui.NOTIFICATION_ERROR)
    return None


def action_test_login():
    email, password = get_credentials()
    if not email or not password:
        xbmcgui.Dialog().ok('Benshi', "Renseignez d'abord votre e-mail et votre mot de passe.")
        return
    try:
        result = get_api().authenticate(email, password)
    except api.BenshiAuthError as exc:
        xbmcgui.Dialog().ok('Benshi', "Échec de la connexion :\n%s" % exc)
        return
    except api.BenshiError as exc:
        xbmcgui.Dialog().ok('Benshi', "Erreur :\n%s" % exc)
        return
    abo = "actif" if result.is_subscribed else "inactif"
    xbmcgui.Dialog().ok('Benshi', "Connexion réussie.\n\nCompte : %s\nAbonnement : %s"
                        % (result.display_name, abo))


# -------------------------------------------------------------------- Catalogue

def list_root():
    """Menu principal du plugin."""
    xbmcplugin.setPluginCategory(HANDLE, 'Benshi')
    xbmcplugin.setContent(HANDLE, 'videos')
    entries = [('Sélections', get_url(action='selections'))]
    # Une entrée par dimension de filtrage (tranche d'âge, type, thème, pays).
    for label, detail_id, title in api.FILTER_DIMENSIONS:
        entries.append((title, get_url(action='dimension', label=label,
                                       detail_id=detail_id, title=title)))
    entries.append(('Tous les films', get_url(action='allfilms', page=1)))
    entries.append(('Rechercher', get_url(action='search')))
    for label, url in entries:
        item = xbmcgui.ListItem(label=label)
        item.setArt({'icon': ICON, 'thumb': ICON})
        xbmcplugin.addDirectoryItem(HANDLE, url, item, isFolder=True)
    xbmcplugin.endOfDirectory(HANDLE)


def list_dimension(label, detail_id, title):
    """Liste les valeurs d'une dimension (ex. les tranches d'âge) comme dossiers."""
    xbmcplugin.setPluginCategory(HANDLE, title)
    xbmcplugin.setContent(HANDLE, 'videos')
    try:
        values = get_api().get_metadata_values(detail_id)
    except api.BenshiError as exc:
        notify(str(exc), icon=xbmcgui.NOTIFICATION_ERROR)
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return
    for value in values:
        name = value.get('name') or ''
        item = xbmcgui.ListItem(label=name)
        item.setArt(api.picture_art(value.get('picture')) or {'icon': ICON})
        url = get_url(action='filter', label=label, value=value.get('id'),
                      title=name, page=1)
        xbmcplugin.addDirectoryItem(HANDLE, url, item, isFolder=True)
    xbmcplugin.endOfDirectory(HANDLE)


def list_filter(label, value, title, page):
    """Liste les films filtrés sur une valeur de dimension (paginé)."""
    xbmcplugin.setPluginCategory(HANDLE, title)
    xbmcplugin.setContent(HANDLE, 'movies')
    try:
        programs, pagination = get_api().filter_programs(label, value, page=page, count=PAGE_SIZE)
    except api.BenshiError as exc:
        notify(str(exc), icon=xbmcgui.NOTIFICATION_ERROR)
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return
    for program in programs:
        add_program_item(program)
    _add_next_page(pagination, lambda p: get_url(action='filter', label=label,
                                                 value=value, title=title, page=p))
    xbmcplugin.addSortMethod(HANDLE, xbmcplugin.SORT_METHOD_LABEL_IGNORE_THE)
    xbmcplugin.endOfDirectory(HANDLE)


def list_selections():
    xbmcplugin.setPluginCategory(HANDLE, 'Sélections')
    xbmcplugin.setContent(HANDLE, 'videos')
    try:
        selections = get_api().get_selections()
    except api.BenshiError as exc:
        notify(str(exc), icon=xbmcgui.NOTIFICATION_ERROR)
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return
    for sel in selections:
        item = xbmcgui.ListItem(label=sel.get('title') or '')
        item.setArt(api.picture_art(sel.get('picture')) or {'icon': ICON})
        info = item.getVideoInfoTag()
        info.setTitle(sel.get('title') or '')
        if sel.get('description'):
            info.setPlot(sel['description'])
        url = get_url(action='selection', selection_id=sel.get('id'))
        xbmcplugin.addDirectoryItem(HANDLE, url, item, isFolder=True)
    xbmcplugin.endOfDirectory(HANDLE)


def list_selection(selection_id):
    xbmcplugin.setContent(HANDLE, 'movies')
    try:
        title, programs = get_api().get_selection_programs(selection_id)
    except api.BenshiError as exc:
        notify(str(exc), icon=xbmcgui.NOTIFICATION_ERROR)
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return
    xbmcplugin.setPluginCategory(HANDLE, title or 'Sélection')
    for program in programs:
        add_program_item(program)
    xbmcplugin.addSortMethod(HANDLE, xbmcplugin.SORT_METHOD_LABEL_IGNORE_THE)
    xbmcplugin.endOfDirectory(HANDLE)


def list_all_films(page):
    xbmcplugin.setPluginCategory(HANDLE, 'Tous les films')
    xbmcplugin.setContent(HANDLE, 'movies')
    try:
        programs, pagination = get_api().get_programs(page=page, count=PAGE_SIZE)
    except api.BenshiError as exc:
        notify(str(exc), icon=xbmcgui.NOTIFICATION_ERROR)
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return
    for program in programs:
        add_program_item(program)
    _add_next_page(pagination, lambda p: get_url(action='allfilms', page=p))
    xbmcplugin.endOfDirectory(HANDLE)


def do_search(page, query=None):
    if not query:
        query = xbmcgui.Dialog().input('Rechercher un film')
        if not query:
            xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
            return
    xbmcplugin.setPluginCategory(HANDLE, 'Recherche : %s' % query)
    xbmcplugin.setContent(HANDLE, 'movies')
    try:
        programs, pagination = get_api().search_programs(query, page=page, count=PAGE_SIZE)
    except api.BenshiError as exc:
        notify(str(exc), icon=xbmcgui.NOTIFICATION_ERROR)
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return
    if not programs:
        notify("Aucun résultat pour « %s »." % query)
    for program in programs:
        add_program_item(program)
    _add_next_page(pagination, lambda p: get_url(action='search', page=p, query=query))
    xbmcplugin.endOfDirectory(HANDLE)


def add_program_item(program):
    """Ajoute un programme au listing : dossier d'épisodes si série, sinon film jouable."""
    title = program.get('title') or ''
    item = xbmcgui.ListItem(label=title)
    item.setArt(api.picture_art(program.get('picture')) or {'icon': ICON})
    info = item.getVideoInfoTag()
    info.setTitle(title)
    if program.get('synopsis'):
        info.setPlot(program['synopsis'])
    year = program.get('date_aaaa')
    if isinstance(year, int) or (isinstance(year, str) and year.isdigit()):
        info.setYear(int(year))

    if api.is_series(program):
        # Série : on ouvre la liste des épisodes au lieu de lancer la lecture.
        info.setMediaType('tvshow')
        url = get_url(action='serie', serie_id=program.get('serie_id'), title=title)
        xbmcplugin.addDirectoryItem(HANDLE, url, item, isFolder=True)
        return

    info.setMediaType('movie')
    duration = program.get('duration')
    if isinstance(duration, int) and duration > 0:
        info.setDuration(duration)
    item.setProperty('IsPlayable', 'true')
    video_id = api.main_video_id(program)
    if video_id:
        url = get_url(action='play', video_id=video_id)
    else:
        url = get_url(action='play', program_id=program.get('id'))
    xbmcplugin.addDirectoryItem(HANDLE, url, item, isFolder=False)


def list_episodes(serie_id, title):
    """Liste les épisodes d'une série (chacun jouable)."""
    xbmcplugin.setPluginCategory(HANDLE, title)
    xbmcplugin.setContent(HANDLE, 'episodes')
    try:
        episodes = get_api().get_episodes(serie_id)
    except api.BenshiError as exc:
        notify(str(exc), icon=xbmcgui.NOTIFICATION_ERROR)
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return
    for episode in episodes:
        add_program_item(episode)
    xbmcplugin.endOfDirectory(HANDLE)


def _add_next_page(pagination, url_builder):
    """Ajoute un élément « Page suivante » si la pagination le permet."""
    current = pagination.get('current_page') or 1
    last = pagination.get('last_page') or pagination.get('total_pages') or current
    if current < last:
        item = xbmcgui.ListItem(label='Page suivante (%d/%d) »' % (current + 1, last))
        item.setArt({'icon': ICON})
        xbmcplugin.addDirectoryItem(HANDLE, url_builder(current + 1), item, isFolder=True)


def play_program(video_id=None, program_id=None):
    """Résout et lance la lecture d'une vidéo (flux HLS/DASH via InputStream Adaptive)."""
    client = get_api()
    try:
        if not video_id and program_id:
            video_id = api.main_video_id(client.get_program(program_id))
        if not video_id:
            raise api.BenshiError("Vidéo introuvable pour ce programme.")
        video = client.get_video(video_id)
    except api.BenshiError as exc:
        notify(str(exc), icon=xbmcgui.NOTIFICATION_ERROR)
        xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
        return

    stream = api.pick_stream(video)
    if not stream:
        notify("Aucun flux disponible pour cette vidéo.", icon=xbmcgui.NOTIFICATION_ERROR)
        xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
        return

    item = xbmcgui.ListItem(path=stream['url'])
    is_dash = stream['manifest_type'] == 'mpd'
    item.setMimeType('application/dash+xml' if is_dash else 'application/x-mpegURL')
    item.setContentLookup(False)
    # Lecture via InputStream Adaptive (obligatoire pour le DASH).
    item.setProperty('inputstream', 'inputstream.adaptive')
    item.setProperty('inputstream.adaptive.manifest_type', stream['manifest_type'])
    if stream.get('drm_url'):
        item.setProperty('inputstream.adaptive.license_type', 'com.widevine.alpha')
        item.setProperty('inputstream.adaptive.license_key', stream['drm_url'])
    xbmcplugin.setResolvedUrl(HANDLE, True, item)


# ----------------------------------------------------------------------- Router

def router(paramstring):
    params = dict(parse_qsl(paramstring))
    action = params.get('action')

    if action == 'testlogin':
        action_test_login()
        return
    if action == 'selections':
        list_selections()
        return
    if action == 'selection':
        list_selection(params.get('selection_id'))
        return
    if action == 'serie':
        list_episodes(params.get('serie_id'), params.get('title', ''))
        return
    if action == 'dimension':
        list_dimension(params.get('label'), params.get('detail_id'), params.get('title', ''))
        return
    if action == 'filter':
        list_filter(params.get('label'), params.get('value'),
                    params.get('title', ''), int(params.get('page', 1)))
        return
    if action == 'allfilms':
        list_all_films(int(params.get('page', 1)))
        return
    if action == 'search':
        do_search(int(params.get('page', 1)), params.get('query'))
        return
    if action == 'play':
        play_program(video_id=params.get('video_id'), program_id=params.get('program_id'))
        return

    # Racine : on valide l'accès au compte avant d'ouvrir le catalogue.
    if login() is None:
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return
    list_root()


if __name__ == '__main__':
    router(sys.argv[2][1:] if len(sys.argv) > 2 else '')