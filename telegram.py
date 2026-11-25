"""Minimal Telegram Bot API client."""
import json

API = "https://api.telegram.org/bot{token}/{method}"


class Telegram:
    def __init__(self, token, session):
        self.token = token
        self.s = session

    def call(self, method, files=None, **params):
        url = API.format(token=self.token, method=method)
        if files:
            data = {k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in params.items()}
            r = self.s.post(url, data=data, files=files, timeout=30)
        else:
            r = self.s.post(url, json=params, timeout=30)
        body = r.json()
        if not body.get("ok"):
            raise RuntimeError(f"Telegram {method}: {body.get('description')}")
        return body["result"]

    def updates(self, offset):
        return self.call("getUpdates", offset=offset, timeout=0,
                         allowed_updates=["message"])

    def send(self, chat_id, text, button_url=None):
        params = {"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                  "disable_web_page_preview": True}
        if button_url:
            params["reply_markup"] = app_button(button_url)
        return self.call("sendMessage", **params)

    def photo(self, chat_id, path, caption, button_url=None):
        params = {"chat_id": chat_id, "caption": caption[:1024], "parse_mode": "HTML"}
        if button_url:
            params["reply_markup"] = app_button(button_url)
        with open(path, "rb") as f:
            return self.call("sendPhoto", files={"photo": f}, **params)

    def menu_button(self, chat_id, url):
        return self.call("setChatMenuButton", chat_id=chat_id,
                         menu_button={"type": "web_app", "text": "Gold Live",
                                      "web_app": {"url": url}})

    def commands(self):
        return self.call("setMyCommands", commands=[
            {"command": "status", "description": "ស្ថានភាពមាសឥឡូវនេះ"},
            {"command": "balance", "description": "កំណត់ទុន ឧ. /balance 1000"},
            {"command": "risk", "description": "កំណត់ហានិភ័យ % ឧ. /risk 1"},
            {"command": "help", "description": "របៀបប្រើ"},
        ])


def app_button(url):
    return {"inline_keyboard": [[{"text": "📊 បើក Gold Live", "web_app": {"url": url}}]]}
