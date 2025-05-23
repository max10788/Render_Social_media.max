import nltk
import os
import json
import re
import asyncio
import aiohttp
import logging
import datetime
from langdetect import detect
from nltk.corpus import stopwords
from nltk.tokenize import word_tokenize
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from app.core.config import settings
import redis

logger = logging.getLogger(__name__)
redis_client = redis.from_url(settings.REDIS_URL)

class TwitterClient:
    def __init__(self):
        self.client = None
        self.analyzer = SentimentIntensityAnalyzer()
        
        # NLTK-Daten herunterladen
    try:
        nltk.data.find('corpora/stopwords')
    except LookupError:
        logger.info("Downloading NLTK stopwords...")
        nltk.download('stopwords', quiet=True)

    try:
        nltk.data.find('tokenizers/punkt')
    except LookupError:
        logger.info("Downloading NLTK punkt tokenizer...")
        nltk.download('punkt', quiet=True)

    def normalize_text(self, text):
        """Entfernt URLs, Sonderzeichen, Emojis und konvertiert in Kleinbuchstaben."""
        if text is None:
            return ""
        text = re.sub(r"http\S+|www\S+", "", text)
        text = re.sub(r"[^\w\s]", "", text)
        return text.lower()

    def tokenize_and_remove_stopwords(self, text, language="en"):
        """Tokenisiert den Text und entfernt Stop-Wörter basierend auf der Sprache."""
        try:
            stop_words = set(stopwords.words(language))
        except Exception:
            logger.warning(f"Sprache '{language}' nicht unterstützt. Fallback auf Englisch.")
            stop_words = set(stopwords.words("english"))
        tokens = word_tokenize(text)
        filtered_tokens = [word for word in tokens if word not in stop_words]
        return " ".join(filtered_tokens)

    async def fetch_tweets_async(self, username, count):
        """Ruft Tweets für einen bestimmten Benutzer ab."""
        user_id = f"user:{username}"  # Benutzer-ID kann auch anders definiert werden
        allowed, message = self.is_request_allowed(user_id)
        if not allowed:
            logger.error(message)
            return {"error": message}

        if username.startswith("@"):
            username = username[1:]
        url = f"https://api.twitter.com/2/users/by/username/{username}"
        headers = {"Authorization": f"Bearer {settings.TWITTER_BEARER_TOKEN}"}
        params = {"user.fields": "id"}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, params=params) as response:
                    if response.status != 200:
                        logger.error(f"Fehler beim Abrufen der Benutzer-ID: Status {response.status}")
                        return []
                    user_data = await response.json()
                    user_id = user_data["data"]["id"]

                tweets_url = f"https://api.twitter.com/2/users/{user_id}/tweets"
                tweets_params = {"max_results": count, "tweet.fields": "created_at"}
                async with session.get(tweets_url, headers=headers, params=tweets_params) as tweets_response:
                    if tweets_response.status != 200:
                        logger.error(f"Fehler beim Abrufen von Tweets: Status {tweets_response.status}")
                        return []
                    tweets_data = await tweets_response.json()
                    return tweets_data.get("data", [])
        except Exception as e:
            logger.error(f"Fehler beim Abrufen von Tweets: {e}")
            return []
            
    async def fetch_tweets_by_keywords(self, keywords, start_date, end_date, tweet_limit):
        """Sucht und verarbeitet Tweets basierend auf Keywords und Zeitraum."""
        try:
            current_time = datetime.datetime.utcnow()
            search_query = " OR ".join(f'"{keyword}"' for keyword in keywords)
    
            # Validiere und korrigiere Daten
            if isinstance(end_date, datetime.date):
                end_date = datetime.datetime.combine(end_date, datetime.time.max)
            if isinstance(start_date, datetime.date):
                start_date = datetime.datetime.combine(start_date, datetime.time.min)
    
            logger.info(f"Original end_date: {end_date}")
            if end_date > current_time:
                logger.warning(f"End date {end_date} ist in der Zukunft. Setze auf aktuelle Zeit.")
                end_date = current_time - datetime.timedelta(seconds=10)
            logger.info(f"Adjusted end_date: {end_date}")
            
            url = "https://api.twitter.com/2/tweets/search/recent"
            headers = {"Authorization": f"Bearer {settings.TWITTER_BEARER_TOKEN}"}
            params = {
                "query": search_query,
                "start_time": start_date.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "end_time": end_date.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "max_results": min(100, tweet_limit),
                "tweet.fields": "created_at,text,author_id"
            }
            
            processed_tweets = []
            async with aiohttp.ClientSession() as session:
                while len(processed_tweets) < tweet_limit:
                    async with session.get(url, headers=headers, params=params) as response:
                        if response.status != 200:
                            logger.error(f"Twitter API Fehler: Status {response.status}")
                            error_data = await response.json()
                            logger.error(f"Twitter API Error Details: {error_data}")
                            break
                        
                        data = await response.json()
                        if not data.get("data"):
                            break
                        
                        for tweet in data["data"]:
                            processed_tweet = self.extract_tweet_attributes(tweet["text"])
                            processed_tweet.update({
                                "id": tweet["id"],
                                "created_at": tweet["created_at"],
                                "author_id": tweet["author_id"]
                            })
                            processed_tweets.append(processed_tweet)
                            
                            if len(processed_tweets) >= tweet_limit:
                                break
                        
                        if "next_token" not in data.get("meta", {}):
                            break
                        
                        params["pagination_token"] = data["meta"]["next_token"]
                        await asyncio.sleep(1)
            
            return processed_tweets[:tweet_limit]
            
        except Exception as e:
            logger.error(f"Fehler beim Abrufen von Tweets: {e}")
            return []

    def extract_tweet_attributes(self, tweet_text):
        """Extrahiert relevante Attribute aus einem Tweet."""
        normalized_text = self.normalize_text(tweet_text)
        language = self.detect_language(normalized_text)
        processed_text = self.tokenize_and_remove_stopwords(normalized_text, language)
        return {
            "text": tweet_text,
            "processed_text": processed_text,
            "keywords": self.extract_keywords(processed_text),
            "amount": self.extract_amount(tweet_text),
            "addresses": self.extract_addresses(tweet_text),
            "hashtags": self.extract_hashtags(tweet_text),
            "links": self.extract_links(tweet_text)
        }

    def extract_keywords(self, text):
        """Extrahiert relevante Schlüsselwörter."""
        relevant_keywords = [
            "solana", "ethereum", "btc", "transfer", "send", "receive",
            "wallet", "transaction", "mint", "burn", "staking", "nft"
        ]
        return [word for word in text.split() if word.lower() in relevant_keywords]

    def extract_amount(self, text):
        """Extrahiert Beträge mit Einheiten."""
        try:
            match = re.search(r"(\d+\.?\d*)\s?(SOL|ETH|BTC|USDT|USDC)", text.upper())
            return float(match.group(1)) if match else None
        except Exception as e:
            logger.error(f"Fehler beim Extrahieren des Betrags: {e}")
            return None

    def extract_addresses(self, text):
        """Extrahiert Ethereum- und Solana-Wallet-Adressen."""
        ethereum_addresses = re.findall(r"0x[a-fA-F0-9]{40}", text)
        solana_addresses = re.findall(r"[1-9A-HJ-NP-Za-km-z]{32,44}", text)
        return ethereum_addresses + solana_addresses

    def extract_hashtags(self, text):
        """Extrahiert Hashtags."""
        return re.findall(r"#\w+", text)

    def extract_links(self, text):
        """Extrahiert URLs."""
        return re.findall(r"https?://[^\s]+", text)
        
    def detect_language(self, text):
        """Erkennt die Sprache eines Textes."""
        try:
            language = detect(text)
            logger.info(f"Detected language: {language}")
            return language
        except Exception:
            logger.warning("Spracherkennung fehlgeschlagen. Fallback auf Englisch.")
            return "en"

    def __init__(self):
        # Bestehender Code...
        self.user_request_limits = {}  # Speichert die Anfragen pro Benutzer
        self.app_request_count = 0
        self.app_request_reset_time = datetime.datetime.utcnow() + datetime.timedelta(days=1)

    def is_request_allowed(self, user_id):
        """
        Überprüft, ob eine Anfrage für einen Benutzer oder die App erlaubt ist.
        """
        current_time = datetime.datetime.utcnow()

        # Benutzerlimit überprüfen
        if user_id in self.user_request_limits:
            user_data = self.user_request_limits[user_id]
            if user_data["count"] >= 17 and current_time < user_data["reset_time"]:
                retry_after = (user_data["reset_time"] - current_time).total_seconds()
                return False, f"Benutzerlimit erreicht. Versuchen Sie es in {int(retry_after // 3600)} Stunden erneut."
            elif current_time >= user_data["reset_time"]:
                # Benutzerlimit zurücksetzen
                self.user_request_limits[user_id] = {"count": 0, "reset_time": current_time + datetime.timedelta(days=1)}
        else:
            self.user_request_limits[user_id] = {"count": 0, "reset_time": current_time + datetime.timedelta(days=1)}

        # Applimit überprüfen
        if self.app_request_count >= 17 and current_time < self.app_request_reset_time:
            retry_after = (self.app_request_reset_time - current_time).total_seconds()
            return False, f"App-Limit erreicht. Versuchen Sie es in {int(retry_after // 3600)} Stunden erneut."
        elif current_time >= self.app_request_reset_time:
            # Applimit zurücksetzen
            self.app_request_count = 0
            self.app_request_reset_time = current_time + datetime.timedelta(days=1)

        # Anfrage erlauben
        self.user_request_limits[user_id]["count"] += 1
        self.app_request_count += 1
        return True, None

    # ==============================
    # Tweets mit Caching
    # ==============================
    async def fetch_and_cache_tweets(self, username, count):
        """
        Ruft Tweets ab und speichert sie im Cache.
        Args:
            username (str): Der Twitter-Benutzername.
            count (int): Die Anzahl der abzurufenden Tweets.
        Returns:
            list: Eine Liste verarbeiteter Tweets.
        """
        cache_key = f"tweets:{username}:{count}"
        cached_tweets = redis_client.get(cache_key)
        if cached_tweets:
            logger.info(f"Tweets für '{username}' aus dem Cache geladen.")
            return json.loads(cached_tweets)
        tweets = await self.fetch_tweets_async(username, count)
        processed_tweets = [self.extract_tweet_attributes(tweet["text"]) for tweet in tweets]
        redis_client.set(cache_key, json.dumps(processed_tweets), ex=3600)  # Cache für 1 Stunde
        logger.info(f"{len(processed_tweets)} Tweets für '{username}' gespeichert.")
        return processed_tweets


# ==============================
# Hilfsfunktion: Tweets in Datei speichern
# ==============================
def save_tweets_to_file(tweets, save_path="data/tweets.json"):
    """Speichert Tweets im JSON-Format."""
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    with open(save_path, "w", encoding="utf-8") as f:
        json.dump(tweets, f, ensure_ascii=False, indent=4)
    logger.info(f"{len(tweets)} Tweets wurden gespeichert in {save_path}")
