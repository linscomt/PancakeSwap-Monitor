import logging
import os
import json
import time
from datetime import datetime
from requests import ConnectionError, HTTPError

from helpers.telegram import Telegram
from .pcsapi import PancakeSwapAPI

API_UPDATE_INTERVAL = 300

def pcs_timestamp_to_str(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp/1000).strftime("%Y-%m-%d %H:%M:%S")

class PCSMonitor:
    LOCAL_DATABASE_FILE = os.path.join('.cache','pcs_token.json')

    def __init__(self, telegram: Telegram) -> None:
        self._logger = logging.getLogger(__name__)
        self._telegram = telegram
        self._prev_server_time = 0
        self._pcs_api = PancakeSwapAPI()

    def start_monitor(self) -> None:
        self._initiate_monitor()
        while True:
            data = self._request_data()
            if data is None:
                time.sleep(1)
                continue
            server_time = data['updated_at']
            if server_time <= self._prev_server_time:
                t_minus = (API_UPDATE_INTERVAL - time.time() + server_time/1000)
                if t_minus < 0:
                    t_minus = 1
                else:
                    self._logger.info(f'Taking a nap of {int(t_minus/60)}min {int(t_minus%60)}s while waiting for the next server update.')
                time.sleep(t_minus)
                continue
            self._logger.info(f'Server updated. Server time: {pcs_timestamp_to_str(server_time)}.')
            self._prev_server_time = server_time
            tokens = data['data']

            self._handle_new_tokens(self._get_new_tokens(tokens), server_time)

    def _initiate_monitor(self) -> None:
        self._logger.info('PancakeSwap Monitor initiating.')
        if os.path.exists(PCSMonitor.LOCAL_DATABASE_FILE):
            self._read_local_database()
        else:
            self._force_update_local_database()
        self._logger.info('PancakeSwap Monitor initiated.')

    def _request_data(self) -> dict:
        try:
            data = self._pcs_api.tokens()
        except ConnectionError:
            self._logger.error('Fail to connect to PancakeSwap server.', exc_info=True)
            return None
        except HTTPError as err:
            self._logger.error(f'PancakeSwap server responded with status code {err.response.status_code}.')
            self._logger.error(f'Full response: {err.response.text}')
            return None
        self._logger.debug('PancakeSwap server responded with status code 200.')
        return data

    def _get_new_tokens(self, new_tokens_data: dict) -> list:
        new_token_keys = new_tokens_data.keys()

        newly_added_tokens = []
        for new_token_key in new_token_keys:
            if new_token_key not in self._saved_token_address:
                self._telegram.send_message_to_users(f'New token found: {Telegram.token_to_message(new_tokens_data[new_token_key])}')
                self._logger.info(f'New token found: {new_tokens_data[new_token_key]}')
                newly_added_tokens.append(new_token_key)

        return newly_added_tokens

    def _handle_new_tokens(self, tokens: dict, server_time: int) -> None:
        if tokens: 
            self._saved_token_address.update(tokens)
        else:
            self._logger.info(f'No new token found.')
        self._saved_token_time = server_time
        self._save_to_local_database()

    def _read_local_database(self) -> None:
        data = json.load(open(PCSMonitor.LOCAL_DATABASE_FILE, 'r'))  # type: dict
        server_time = data['updated_at']
        if time.time() - server_time > 86400000:
            self._force_update_local_database()
        self._saved_token_time = server_time
        self._saved_token_address = set(data['data'])
        self._logger.info(f'Local database loaded. Database time: {pcs_timestamp_to_str(server_time)}.')

    def _force_update_local_database(self) -> None:
        self._logger.info('Local database does not exist or is out of date. Updating local database.')
        while True:
            data = self._request_data()
            if data is None:
                time.sleep(10)
                continue
            self._saved_token_time = data['updated_at']
            self._saved_token_address = set(data['data'].keys())
            self._save_to_local_database()
            break

    def _save_to_local_database(self) -> None:
        json.dump({'updated_at': self._saved_token_time, 'data': list(self._saved_token_address)}, open(PCSMonitor.LOCAL_DATABASE_FILE, 'w+'))
        msg = f'Local database has been updated successfully. Server time: {pcs_timestamp_to_str(self._saved_token_time)}.'
        self._logger.info(msg)
        self._telegram.send_message_to_admin(msg)
