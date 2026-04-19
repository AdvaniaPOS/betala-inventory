"""
Betala API Client.

Klient for å kommunisere med Betala POS API for å hente produkter og salgsdata.
Basert på Betala API v2.0 dokumentasjon.
"""

import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, date
from dataclasses import dataclass

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)


@dataclass
class BetalaConfig:
    """Konfigurasjon for Betala API."""
    base_url: str
    api_key: str
    organization_id: str
    timeout: int = 30


class BetalaAPIError(Exception):
    """Feil ved API-kall til Betala."""
    def __init__(self, message: str, status_code: int = None, response_data: dict = None):
        self.message = message
        self.status_code = status_code
        self.response_data = response_data
        super().__init__(self.message)


class BetalaClient:
    """
    Asynkron klient for Betala API.
    
    Eksempel:
        async with BetalaClient() as client:
            products = await client.get_products()
            sales = await client.get_sales(date.today())
    """
    
    def __init__(self, config: BetalaConfig = None):
        if config is None:
            config = BetalaConfig(
                base_url=settings.BETALA_API_URL,
                api_key=settings.BETALA_API_KEY,
                organization_id=settings.BETALA_ORGANIZATION_ID,
            )
        self.config = config
        self._client: Optional[httpx.AsyncClient] = None
    
    async def __aenter__(self):
        self._client = httpx.AsyncClient(
            base_url=self.config.base_url,
            timeout=self.config.timeout,
            headers=self._get_headers(),
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._client:
            await self._client.aclose()
    
    def _get_headers(self) -> dict:
        """Returner HTTP-headere for API-kall."""
        return {
            'Authorization': f'Bearer {self.config.api_key}',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }
    
    async def _request(
        self,
        method: str,
        endpoint: str,
        params: dict = None,
        data: dict = None
    ) -> dict:
        """Utfør HTTP-request til Betala API."""
        try:
            response = await self._client.request(
                method=method,
                url=endpoint,
                params=params,
                json=data,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"Betala API feil: {e.response.status_code} - {e.response.text}")
            raise BetalaAPIError(
                message=f"API-feil: {e.response.status_code}",
                status_code=e.response.status_code,
                response_data=e.response.json() if e.response.content else None
            )
        except httpx.RequestError as e:
            logger.error(f"Betala tilkoblingsfeil: {e}")
            raise BetalaAPIError(f"Tilkoblingsfeil: {e}")
    
    # =========================================================================
    # AUTENTISERING
    # =========================================================================
    
    async def authenticate(self, email: str, password: str) -> dict:
        """Autentiser bruker mot Betala."""
        return await self._request(
            'POST',
            '/api/v2.0/users/_auth',
            data={'email': email, 'password': password}
        )
    
    # =========================================================================
    # ORGANISASJON
    # =========================================================================
    
    async def get_organization(self, org_id: int = None) -> dict:
        """Hent organisasjonsinformasjon."""
        org_id = org_id or self.config.organization_id
        return await self._request('GET', f'/api/v2.0/organizations/{org_id}')
    
    # =========================================================================
    # PRODUKTER
    # =========================================================================
    
    async def get_products(
        self,
        org_id: int = None,
        include_archived: bool = False
    ) -> List[dict]:
        """
        Hent alle produkter for organisasjonen.
        
        Returns:
            Liste med produkter med felter som:
            - product_id, name, description, price, vat, vat_factor
            - category_id, article_group_id, is_archived, etc.
        """
        org_id = org_id or self.config.organization_id
        params = {}
        if include_archived:
            params['include_archived'] = 'true'
        
        response = await self._request(
            'GET',
            f'/api/v2.0/organizations/{org_id}/products',
            params=params
        )
        return response.get('data', [])
    
    async def get_product(self, product_id: int, org_id: int = None) -> dict:
        """Hent et enkelt produkt."""
        org_id = org_id or self.config.organization_id
        response = await self._request(
            'GET',
            f'/api/v2.0/organizations/{org_id}/products/{product_id}'
        )
        return response.get('data', {})
    
    async def update_product(
        self,
        product_id: int,
        data: dict,
        org_id: int = None
    ) -> dict:
        """
        Oppdater et produkt i Betala.
        
        Args:
            product_id: Betala produkt-ID
            data: Produktdata-payload (må inkludere price_with_vat, ikke price/vat)
            org_id: Organisasjons-ID
        
        Returns:
            Oppdatert produktdata fra API
        """
        org_id = org_id or self.config.organization_id
        
        response = await self._request(
            'POST',
            f'/api/v2.0/organizations/{org_id}/products/{product_id}/_edit',
            data=data
        )
        return response.get('data', {})
    
    # =========================================================================
    # KATEGORIER
    # =========================================================================
    
    async def get_categories(self, org_id: int = None) -> List[dict]:
        """Hent alle produktkategorier."""
        org_id = org_id or self.config.organization_id
        response = await self._request(
            'GET',
            f'/api/v2.0/organizations/{org_id}/product_categories'
        )
        return response.get('data', [])
    
    # =========================================================================
    # SALGSPUNKTER
    # =========================================================================
    
    async def get_sales_point_groups(self, org_id: int = None) -> List[dict]:
        """Hent salgspunktgrupper (hierarki for kasser)."""
        org_id = org_id or self.config.organization_id
        response = await self._request(
            'GET',
            f'/api/v2.0/organizations/{org_id}/sales_point_groups'
        )
        return response.get('data', [])
    
    async def get_sales_points(
        self,
        sales_point_group_id: int,
        org_id: int = None
    ) -> List[dict]:
        """Hent salgspunkter for en gruppe."""
        org_id = org_id or self.config.organization_id
        response = await self._request(
            'GET',
            f'/api/v2.0/organizations/{org_id}/sales_point_groups/{sales_point_group_id}/sales_points'
        )
        return response.get('data', [])
    
    # =========================================================================
    # SALG / KJØP
    # =========================================================================
    
    async def get_purchases(
        self,
        sales_point_group_id: int,
        start_date: date = None,
        end_date: date = None,
        org_id: int = None,
        limit: int = 1000,
        offset: int = 0
    ) -> List[dict]:
        """
        Hent kjøp/salg for en salgspunktgruppe.
        
        Returns:
            Liste med kjøp inkludert:
            - pos_purchase_id, device_id, sales_point_id
            - created_at, finalized_at
            - purchase_products (linjer med produkt, antall, pris)
            - transactions (betalingstransaksjoner)
        """
        org_id = org_id or self.config.organization_id
        params = {
            'limit': limit,
            'offset': offset,
        }
        if start_date:
            params['start'] = start_date.isoformat()
        if end_date:
            params['end'] = end_date.isoformat()
        
        response = await self._request(
            'GET',
            f'/api/v2.0/organizations/{org_id}/sales_point_groups/{sales_point_group_id}/purchases',
            params=params
        )
        return response.get('data', [])
    
    async def get_purchase(
        self,
        purchase_id: str,
        org_id: int = None
    ) -> dict:
        """Hent detaljer for et enkelt kjøp."""
        org_id = org_id or self.config.organization_id
        response = await self._request(
            'GET',
            f'/api/v2.0/organizations/{org_id}/purchases/{purchase_id}'
        )
        return response.get('data', {})
    
    # =========================================================================
    # STATISTIKK
    # =========================================================================
    
    async def get_sales_stats(
        self,
        sales_point_group_id: int,
        start_date: date = None,
        end_date: date = None,
        org_id: int = None
    ) -> dict:
        """
        Hent salgsstatistikk for en periode.
        
        Returns:
            Aggregert statistikk med totaler per produkt, kategori, etc.
        """
        org_id = org_id or self.config.organization_id
        params = {}
        if start_date:
            params['start'] = start_date.isoformat()
        if end_date:
            params['end'] = end_date.isoformat()
        
        response = await self._request(
            'GET',
            f'/api/v2.0/organizations/{org_id}/sales_point_groups/{sales_point_group_id}/stats',
            params=params
        )
        return response.get('data', {})
    
    async def get_product_stats(
        self,
        sales_point_group_id: int,
        start_date: date = None,
        end_date: date = None,
        org_id: int = None
    ) -> List[dict]:
        """
        Hent salgsstatistikk per produkt.
        
        Returns:
            Liste med produktstatistikk:
            - product_id, name, quantity_sold, total_revenue, etc.
        """
        org_id = org_id or self.config.organization_id
        params = {}
        if start_date:
            params['start'] = start_date.isoformat()
        if end_date:
            params['end'] = end_date.isoformat()
        
        response = await self._request(
            'GET',
            f'/api/v2.0/organizations/{org_id}/sales_point_groups/{sales_point_group_id}/product_stats',
            params=params
        )
        return response.get('data', [])

    # =========================================================================
    # TRANSAKSJONER
    # =========================================================================

    async def get_transactions(
        self,
        sales_point_group_id: int,
        org_id: int = None,
        from_date: date = None,
        to_date: date = None,
        limit: int = 1000,
        offset: int = 0
    ) -> List[dict]:
        """
        Hent transaksjoner for en salgspunktgruppe.
        
        Args:
            sales_point_group_id: ID for salgspunktgruppen
            org_id: Organisasjons-ID (bruker config hvis ikke oppgitt)
            from_date: Startdato for filtrering (inklusiv)
            to_date: Sluttdato for filtrering (inklusiv)
            limit: Maks antall resultater per kall
            offset: Antall resultater å hoppe over (for paginering)
        
        Returns:
            Liste med transaksjoner
        """
        org_id = org_id or self.config.organization_id
        params = {
            'limit': limit,
            'offset': offset,
        }
        if from_date:
            params['from'] = from_date.isoformat()
        if to_date:
            params['to'] = to_date.isoformat()
        
        response = await self._request(
            'GET',
            f'/api/v2.0/organizations/{org_id}/sales_point_groups/{sales_point_group_id}/transactions',
            params=params
        )
        return response.get('transactions', [])


# =============================================================================
# AUTENTISERING (statisk funksjon)
# =============================================================================

def authenticate_betala(email: str, password: str, base_url: str = None) -> dict:
    """
    Autentiser mot Betala API og hent token + organisasjoner.
    
    Args:
        email: Brukerens e-postadresse
        password: Brukerens passord
        base_url: API base URL (default: settings.BETALA_API_URL)
    
    Returns:
        dict med 'token', 'user' og 'organizations'
    
    Raises:
        BetalaAPIError: Ved feil autentisering
    """
    if base_url is None:
        base_url = settings.BETALA_API_URL
    
    try:
        response = httpx.post(
            f'{base_url}/api/v2.0/users/_auth',
            json={'email': email, 'password': password},
            timeout=30
        )
        response.raise_for_status()
        
        data = response.json()
        token = response.headers.get('authorization-token')
        
        if not token:
            raise BetalaAPIError("Ingen token mottatt fra API")
        
        return {
            'token': token,
            'user': data.get('data', {}).get('user', {}),
            'organizations': data.get('data', {}).get('organizations', []),
        }
        
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            raise BetalaAPIError("Feil e-post eller passord", status_code=401)
        raise BetalaAPIError(
            f"Autentiseringsfeil: {e.response.status_code}",
            status_code=e.response.status_code
        )
    except httpx.RequestError as e:
        raise BetalaAPIError(f"Tilkoblingsfeil: {e}")


# =============================================================================
# SYNKRON KLIENT (for Django management commands)
# =============================================================================

class BetalaClientSync:
    """
    Synkron versjon av Betala-klienten.
    
    Brukes i management commands og bakgrunnsjobber hvor async ikke er nødvendig.
    """
    
    def __init__(self, config: BetalaConfig = None):
        if config is None:
            config = BetalaConfig(
                base_url=settings.BETALA_API_URL,
                api_key=settings.BETALA_API_KEY,
                organization_id=settings.BETALA_ORGANIZATION_ID,
            )
        self.config = config
        self._client = httpx.Client(
            base_url=self.config.base_url,
            timeout=self.config.timeout,
            headers=self._get_headers(),
        )
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self._client.close()
    
    def _get_headers(self) -> dict:
        return {
            'Authorization': f'Bearer {self.config.api_key}',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }
    
    def _request(
        self,
        method: str,
        endpoint: str,
        params: dict = None,
        data: dict = None
    ) -> dict:
        """Utfør synkron HTTP-request til Betala API."""
        try:
            response = self._client.request(
                method=method,
                url=endpoint,
                params=params,
                json=data,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"Betala API feil: {e.response.status_code} - {e.response.text}")
            raise BetalaAPIError(
                message=f"API-feil: {e.response.status_code}",
                status_code=e.response.status_code,
                response_data=e.response.json() if e.response.content else None
            )
        except httpx.RequestError as e:
            logger.error(f"Betala tilkoblingsfeil: {e}")
            raise BetalaAPIError(f"Tilkoblingsfeil: {e}")
    
    def get_products(
        self,
        org_id: int = None,
        include_archived: bool = False
    ) -> List[dict]:
        """Hent alle produkter."""
        org_id = org_id or self.config.organization_id
        params = {}
        if include_archived:
            params['include_archived'] = 'true'
        
        response = self._request(
            'GET',
            f'/api/v2.0/organizations/{org_id}/products',
            params=params
        )
        return response.get('data', [])
    
    def get_categories(self, org_id: int = None) -> List[dict]:
        """Hent alle kategorier."""
        org_id = org_id or self.config.organization_id
        response = self._request(
            'GET',
            f'/api/v2.0/organizations/{org_id}/product_categories'
        )
        return response.get('data', [])
    
    def get_purchases(
        self,
        sales_point_group_id: int,
        start_date: date = None,
        end_date: date = None,
        org_id: int = None,
        limit: int = 1000,
        offset: int = 0
    ) -> List[dict]:
        """Hent kjøp/salg."""
        org_id = org_id or self.config.organization_id
        params = {
            'limit': limit,
            'offset': offset,
        }
        if start_date:
            params['start'] = start_date.isoformat()
        if end_date:
            params['end'] = end_date.isoformat()
        
        response = self._request(
            'GET',
            f'/api/v2.0/organizations/{org_id}/sales_point_groups/{sales_point_group_id}/purchases',
            params=params
        )
        return response.get('data', [])
    
    def get_sales_point_groups(self, org_id: int = None) -> List[dict]:
        """Hent salgspunktgrupper."""
        org_id = org_id or self.config.organization_id
        response = self._request(
            'GET',
            f'/api/v2.0/organizations/{org_id}/sales_point_groups'
        )
        return response.get('data', [])

    def get_transactions(
        self,
        sales_point_group_id: int,
        org_id: int = None,
        from_date: date = None,
        to_date: date = None,
        limit: int = 1000,
        offset: int = 0
    ) -> List[dict]:
        """
        Hent transaksjoner for en salgspunktgruppe.
        
        Args:
            sales_point_group_id: ID for salgspunktgruppen
            org_id: Organisasjons-ID (bruker config hvis ikke oppgitt)
            from_date: Startdato for filtrering (inklusiv)
            to_date: Sluttdato for filtrering (inklusiv)
            limit: Maks antall resultater per kall
            offset: Antall resultater å hoppe over (for paginering)
        
        Returns:
            Liste med transaksjoner, hver med:
            - transaction: {sequence_number, finalized, is_void, ...}
            - payments: [{payment_id, amount, payment_type}, ...]
            - products: [{product_id, name, price, vat, ...}, ...]
        """
        org_id = org_id or self.config.organization_id
        params = {
            'limit': limit,
            'offset': offset,
        }
        if from_date:
            params['from'] = from_date.isoformat()
        if to_date:
            params['to'] = to_date.isoformat()
        
        response = self._request(
            'GET',
            f'/api/v2.0/organizations/{org_id}/sales_point_groups/{sales_point_group_id}/transactions',
            params=params
        )
        return response.get('transactions', [])

    def get_sales_point_areas(
        self,
        org_id: int = None,
        is_archived: bool = False
    ) -> List[dict]:
        """
        Hent salgspunkt-områder for en organisasjon.
        
        Args:
            org_id: Organisasjons-ID
            is_archived: Hent arkiverte områder (default: False)
        
        Returns:
            Liste med salgspunkt-områder
        """
        org_id = org_id or self.config.organization_id
        params = {'is_archived': str(is_archived).lower()}
        
        response = self._request(
            'GET',
            f'/api/v2.0/organizations/{org_id}/sales_point_areas/',
            params=params
        )
        return response.get('data', [])
    
    def update_product(
        self,
        product_id: int,
        data: dict,
        org_id: int = None
    ) -> dict:
        """
        Oppdater et produkt i Betala.
        
        Args:
            product_id: Betala produkt-ID
            data: Produktdata-payload
            org_id: Organisasjons-ID
        
        Returns:
            Oppdatert produktdata fra API
        """
        org_id = org_id or self.config.organization_id
        
        response = self._request(
            'POST',
            f'/api/v2.0/organizations/{org_id}/products/{product_id}/_edit',
            data=data
        )
        return response.get('data', {})


def get_sales_point_areas(token: str, org_id: str, is_archived: bool = False, base_url: str = None) -> List[dict]:
    """
    Hent salgspunkt-områder for en organisasjon.
    
    Args:
        token: Betala auth token
        org_id: Organisasjons-ID
        is_archived: Hent arkiverte områder
        base_url: API base URL
    
    Returns:
        Liste med salgspunkt-områder
    """
    if base_url is None:
        base_url = settings.BETALA_API_URL
    
    try:
        response = httpx.get(
            f'{base_url}/api/v2.0/organizations/{org_id}/sales_point_areas/',
            params={'is_archived': str(is_archived).lower()},
            headers={
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json',
            },
            timeout=30
        )
        response.raise_for_status()
        data = response.json()
        
        # API kan returnere liste direkte eller objekt med 'data'-nøkkel
        if isinstance(data, list):
            return data
        return data.get('data', [])
        
    except httpx.HTTPStatusError as e:
        raise BetalaAPIError(
            f"Kunne ikke hente salgspunkt-områder: {e.response.status_code}",
            status_code=e.response.status_code
        )
    except httpx.RequestError as e:
        raise BetalaAPIError(f"Tilkoblingsfeil: {e}")
