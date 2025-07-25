from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
from sqlalchemy.orm import Session
from app.core.backend_crypto_tracker.utils.logger import get_logger
logger = get_logger(__name__)

# Services
from app.core.backend_crypto_tracker.services.btc.transaction_service import BlockchairBTCClient
from app.core.backend_crypto_tracker.services.eth.etherscan_api import EtherscanETHClient
from app.core.backend_crypto_tracker.services.sol.solana_api import SolanaAPIClient

# Database
from app.core.backend_crypto_tracker.database.models.transaction_model import Transaction
from app.core.backend_crypto_tracker.database.base import Base

from app.core.database import get_db

router = APIRouter()

class TrackTransactionRequest(BaseModel):
    blockchain: str  # "btc", "eth", "sol"
    tx_hash: str
    depth: int = 3  # Maximale Transaktionsketten-Tiefe
    include_metadata: bool = True

class TransactionResponse(BaseModel):
    tx_hash: str
    chain: str
    timestamp: datetime
    from_address: Optional[str]
    to_address: Optional[str]
    amount: float
    currency: str
    next_transactions: List["TransactionResponse"] = []

# Rekursive Modellreferenz
TransactionResponse.update_forward_refs()

@router.post("/track", response_model=TransactionResponse)
def track_transaction(
    request: TrackTransactionRequest,
    db: Session = Depends(get_db)
):
    try:
        logger.info(f"START: Transaktionsverfolgung gestartet für Blockchain '{request.blockchain}' mit Hash '{request.tx_hash}'")
        
        # 1. Blockchain-Client auswählen
        logger.debug(f"Schritt 1: Blockchain-Client wird ausgewählt für '{request.blockchain}'")
        if request.blockchain == "btc":
            logger.info("Blockchain-Client: BlockchairBTCClient wird verwendet")
            client = BlockchairBTCClient()
        elif request.blockchain == "eth":
            logger.info("Blockchain-Client: EtherscanETHClient wird verwendet")
            client = EtherscanETHClient()
        elif request.blockchain == "sol":
            logger.info("Blockchain-Client: SolanaAPIClient wird verwendet")
            client = SolanaAPIClient()
        else:
            logger.error(f"Ungültige Blockchain angegeben: '{request.blockchain}'")
            raise HTTPException(status_code=400, detail="Unsupported blockchain")
        
        # 2. Transaktionsdetails abrufen
        logger.debug(f"Schritt 2: Transaktionsdetails werden abgerufen für Hash '{request.tx_hash}'")
        try:
            logger.info(f"Aufruf: client.get_transaction('{request.tx_hash}') wird ausgeführt")
            raw_data = client.get_transaction(request.tx_hash)
            logger.info(f"Erfolg: Transaktionsdetails erfolgreich abgerufen (Rohdaten erhalten)")
        except Exception as e:
            logger.error(f"Fehler bei Abruf der Transaktionsdetails: {str(e)}", exc_info=True)
            raise HTTPException(status_code=400, detail=f"Invalid transaction hash: {str(e)}")
        
        # 3. Daten parsen
        logger.debug("Schritt 3: Transaktionsdaten werden geparsed")
        try:
            logger.info("Aufruf: BlockchainParser().parse_transaction() wird gestartet")
            parser = BlockchainParser()
            parsed_data = parser.parse_transaction(request.blockchain, raw_data)
            logger.info(f"Erfolg: Transaktionsdaten erfolgreich geparsed (Amount: {parsed_data.get('amount')}, From: {parsed_data.get('from_address')[:10]}...)")
        except Exception as e:
            logger.error(f"Fehler beim Parsen der Transaktionsdaten: {str(e)}", exc_info=True)
            logger.debug(f"Rohdatenstruktur (erste 500 Zeichen): {str(raw_data)[:500]}")
            raise HTTPException(status_code=400, detail=f"Could not parse transaction: {str(e)}")
        
        # 4. In DB speichern
        logger.debug("Schritt 4: Transaktionsdaten werden in die Datenbank gespeichert")
        try:
            logger.info(f"DB-Speicherung: Neue Transaktion mit Hash '{parsed_data['tx_hash']}' wird vorbereitet")
            db_transaction = Transaction(
                hash=parsed_data["tx_hash"],
                chain=parsed_data["chain"],
                timestamp=parsed_data["timestamp"],
                raw_data=raw_data,
                parsed_data=parsed_data
            )
            logger.debug(f"DB: Transaktionsobjekt erstellt: {db_transaction}")
            db.add(db_transaction)
            db.commit()
            db.refresh(db_transaction)
            logger.info(f"Erfolg: Transaktion erfolgreich in DB gespeichert (ID: {db_transaction.id})")
        except Exception as e:
            logger.error(f"Fehler bei DB-Speicherung: {str(e)}", exc_info=True)
            raise HTTPException(status_code=500, detail="Database error")
        
        # 5. Rekursive Verarbeitung
        logger.debug(f"Schritt 5: Rekursive Verarbeitung wird gestartet (Tiefe: {request.depth})")
        next_transactions = []
        if request.depth > 1:
            logger.info(f"Rekursion: Verarbeite nächste Transaktionen (Tiefe: {request.depth-1})")
            
            # WICHTIG: Nutze _get_next_transactions für die korrekte Transaktionskette
            if parsed_data["to_address"]:
                logger.debug(f"Suche nach nächsten Transaktionen für Zieladresse: {parsed_data['to_address']}")
                next_hashes = parser._get_next_transactions(
                    request.blockchain,
                    parsed_data["to_address"],
                    current_hash=parsed_data["tx_hash"],
                    limit=5
                )
                
                logger.info(f"Gefundene nächste Transaktionen: {len(next_hashes)}")
                for next_hash in next_hashes:
                    logger.debug(f"Verarbeite nächste Transaktion: {next_hash}")
                    next_request = TrackTransactionRequest(
                        blockchain=request.blockchain,
                        tx_hash=next_hash,
                        depth=request.depth - 1
                    )
                    try:
                        next_result = track_transaction(next_request, db)
                        next_transactions.append(next_result)
                        logger.debug(f"Transaktion erfolgreich verarbeitet: {next_hash}")
                    except Exception as e:
                        logger.error(f"Fehler bei Verarbeitung von {next_hash}: {str(e)}", exc_info=True)
            
            logger.info(f"Rekursion: {len(next_transactions)} nächste Transaktionen verarbeitet")
        
        # 6. Antwort vorbereiten
        logger.debug("Schritt 6: API-Antwort wird vorbereitet")
        response = {
            "tx_hash": parsed_data["tx_hash"],
            "chain": parsed_data["chain"],
            "timestamp": parsed_data["timestamp"],
            "from_address": parsed_data["from_address"],
            "to_address": parsed_data["to_address"],
            "amount": parsed_data["amount"],
            "currency": parsed_data["currency"],
            "next_transactions": next_transactions
        }
        logger.info(f"ERFOLG: Transaktionsverfolgung abgeschlossen für Hash '{request.tx_hash}'")
        return response
    
    except HTTPException as he:
        logger.warning(f"HTTP-Fehler ({he.status_code}): {he.detail}")
        raise he
    except Exception as e:
        logger.critical(f"UNERWARTETER FEHLER in track_transaction: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
