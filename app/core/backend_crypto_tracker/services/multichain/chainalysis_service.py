# services/multichain/chainalysis_service.py

import httpx
import asyncio
import logging
from typing import Optional, Dict, Any
from config.blockchain_api_keys import get_api_keys

logger = logging.getLogger(__name__)

class ChainalysisIntegration:
    """Enhanced integration with Chainalysis API for professional blockchain analysis"""
    def __init__(self):
        api_keys = get_api_keys()
        self.api_key = api_keys.get('chainalysis')
        if not self.api_key:
            logger.warning("Chainalysis API key not found in config.")
        self.base_url = "https://api.chainalysis.com/api/kyt/v1"
        self.rate_limit_delay = 1.0  # 1 second between requests
        self.session_timeout = 30.0

    async def get_address_risk(self, address: str, asset: str) -> Optional[Dict]:
        """Get comprehensive risk score and entity information from Chainalysis"""
        try:
            headers = {
                "X-API-Key": self.api_key,
                "Content-Type": "application/json"
            }
            
            async with httpx.AsyncClient(timeout=self.session_timeout) as client:
                # Get address information
                response = await client.get(
                    f"{self.base_url}/addresses/{address}",
                    params={"asset": asset},
                    headers=headers
                )
                
                if response.status_code == 200:
                    data = response.json()
                    
                    # Parse and enrich the response
                    enriched_data = {
                        'address': address,
                        'asset': asset,
                        'risk_score': data.get('riskScore', 0),
                        'entity_type': data.get('entityType', ''),
                        'entity_name': data.get('entityName', ''),
                        'category': data.get('category', ''),
                        'total_received': data.get('totalReceived', 0),
                        'total_sent': data.get('totalSent', 0),
                        'first_seen': data.get('firstSeen'),
                        'last_seen': data.get('lastSeen'),
                        'exposure_details': data.get('exposureDetails', {}),
                        'cluster_info': data.get('clusterInfo', {})
                    }
                    
                    await asyncio.sleep(self.rate_limit_delay)  # Rate limiting
                    return enriched_data
                    
                elif response.status_code == 429:  # Rate limit
                    logger.warning("Chainalysis rate limit hit, waiting...")
                    await asyncio.sleep(5.0)
                    return None
                else:
                    logger.warning(f"Chainalysis API error: {response.status_code} - {response.text}")
                    return None
                    
        except asyncio.TimeoutError:
            logger.error("Chainalysis API timeout")
            return None
        except Exception as e:
            logger.error(f"Chainalysis API call failed: {e}")
            return None
    
    async def screen_address(self, address: str) -> Optional[Dict]:
        """Enhanced sanctions screening with detailed violation information"""
        try:
            headers = {
                "X-API-Key": self.api_key,
                "Content-Type": "application/json"
            }
            
            async with httpx.AsyncClient(timeout=self.session_timeout) as client:
                response = await client.get(
                    f"{self.base_url}/addresses/{address}/sanctions",
                    headers=headers
                )
                
                if response.status_code == 200:
                    data = response.json()
                    
                    sanctions_info = {
                        'is_sanctioned': data.get('isSanctioned', False),
                        'sanction_lists': data.get('sanctionLists', []),
                        'violation_type': data.get('violationType', ''),
                        'sanction_date': data.get('sanctionDate'),
                        'jurisdiction': data.get('jurisdiction', ''),
                        'confidence_level': data.get('confidenceLevel', 'medium')
                    }
                    
                    await asyncio.sleep(self.rate_limit_delay)
                    return sanctions_info
                    
                return None
                
        except Exception as e:
            logger.error(f"Sanctions screening failed: {e}")
            return None
    
    async def get_cluster_analysis(self, address: str, asset: str) -> Optional[Dict]:
        """Get cluster analysis for address relationships"""
        try:
            headers = {"X-API-Key": self.api_key}
            
            async with httpx.AsyncClient(timeout=self.session_timeout) as client:
                response = await client.get(
                    f"{self.base_url}/addresses/{address}/cluster",
                    params={"asset": asset},
                    headers=headers
                )
                
                if response.status_code == 200:
                    return response.json()
                return None
                
        except Exception as e:
            logger.error(f"Cluster analysis failed: {e}")
            return None
