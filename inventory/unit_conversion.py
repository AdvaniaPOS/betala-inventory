"""
Enhetskonvertering (Unit of Measure) for lagersystemet.

Dette modulet håndterer konvertering mellom ulike måleenheter for produkter
i utelivsbransjen. Alle mengder lagres internt som heltall i produktets
base-enhet (ml, cl eller stk) for å unngå avrundingsfeil.

Eksempel bruk:
    product = Product.objects.get(name="Fatøl")
    # Produkt har base_unit_type = 'ml' og enheter: Tank 30L, Glass 0.4L
    
    # Ved innkjøp: Mottatt 2 tanker
    result = process_receiving(product, unit_name="Tank 30L", quantity=2, event=event)
    # -> Legger til 60000 ml på lager
    
    # Ved salg: Solgt 5 glass  
    result = process_sale(product, unit_name="Glass 0.4L", quantity=5, event=event)
    # -> Trekker 2000 ml fra lager
    
    # Format for visning
    display = format_stock_display(product, event=event)
    # -> "1 Tank, 15 Glass, 500 ml"
"""

from typing import Optional, Tuple, List, Dict
from decimal import Decimal
from django.db import transaction
from django.utils import timezone


class UnitConversionError(Exception):
    """Feil ved enhetskonvertering."""
    pass


class InsufficientStockError(Exception):
    """Ikke nok på lager."""
    def __init__(self, product, required: int, available: int, unit_name: str = None):
        self.product = product
        self.required = required
        self.available = available
        self.unit_name = unit_name
        super().__init__(
            f"Ikke nok på lager for {product.name}. "
            f"Kreves: {required} {unit_name or product.base_unit_type}, "
            f"Tilgjengelig: {available}"
        )


def get_unit_by_name(product, unit_name: str):
    """
    Hent enhet for et produkt basert på navn.
    
    Args:
        product: Product-objekt
        unit_name: Navn på enheten (f.eks. "Tank 30L")
        
    Returns:
        UnitOfMeasure-objekt
        
    Raises:
        UnitConversionError: Hvis enheten ikke finnes
    """
    from .models import UnitOfMeasure
    
    if not product.use_unit_conversion:
        raise UnitConversionError(
            f"Produktet {product.name} bruker ikke enhetskonvertering"
        )
    
    try:
        return product.units.get(name=unit_name, is_active=True)
    except UnitOfMeasure.DoesNotExist:
        available = list(product.units.filter(is_active=True).values_list('name', flat=True))
        raise UnitConversionError(
            f"Enheten '{unit_name}' finnes ikke for {product.name}. "
            f"Tilgjengelige enheter: {', '.join(available) or 'Ingen'}"
        )


def convert_to_base_units(product, quantity: int, unit_id: int = None, 
                          unit_name: str = None) -> int:
    """
    Konverter en mengde til base-enheter.
    
    Args:
        product: Product-objekt
        quantity: Antall i den gitte enheten
        unit_id: ID til enheten (prioriteres)
        unit_name: Navn på enheten (brukes hvis unit_id ikke er gitt)
        
    Returns:
        Antall i base-enheter (heltall)
        
    Raises:
        UnitConversionError: Ved ugyldig enhet
    """
    if not product.use_unit_conversion:
        return quantity
    
    if unit_id:
        try:
            unit = product.units.get(id=unit_id, is_active=True)
        except Exception:
            raise UnitConversionError(f"Ugyldig enhet-ID: {unit_id}")
    elif unit_name:
        unit = get_unit_by_name(product, unit_name)
    else:
        raise UnitConversionError("Enten unit_id eller unit_name må oppgis")
    
    return unit.to_base_units(quantity)


def convert_from_base_units(product, base_quantity: int, unit_id: int = None,
                            unit_name: str = None) -> Tuple[int, int]:
    """
    Konverter base-enheter til en spesifikk enhet.
    
    Args:
        product: Product-objekt
        base_quantity: Antall i base-enheter
        unit_id: ID til enheten
        unit_name: Navn på enheten
        
    Returns:
        tuple: (hele_enheter, rest_i_base_enheter)
    """
    if not product.use_unit_conversion:
        return base_quantity, 0
    
    if unit_id:
        try:
            unit = product.units.get(id=unit_id, is_active=True)
        except Exception:
            raise UnitConversionError(f"Ugyldig enhet-ID: {unit_id}")
    elif unit_name:
        unit = get_unit_by_name(product, unit_name)
    else:
        raise UnitConversionError("Enten unit_id eller unit_name må oppgis")
    
    return unit.from_base_units(base_quantity)


def format_stock_display(product, base_quantity: int = None, event=None,
                         include_base_remainder: bool = True) -> str:
    """
    Formater lagerbeholdning til menneskelig lesbar streng.
    
    Eksempel: 35500 ml -> "1 Tank 30L, 5 Liter, 500 ml"
    
    Args:
        product: Product-objekt
        base_quantity: Antall i base-enheter (hentes automatisk hvis None)
        event: Filtrer på event
        include_base_remainder: Inkluder rest i base-enheter
        
    Returns:
        Formatert streng
    """
    if base_quantity is None:
        base_quantity = product.get_current_stock(event)
    
    # Hvis produktet ikke bruker enhetskonverering, vis enkel form
    if not product.use_unit_conversion:
        unit = product.unit or product.base_unit_type
        return f"{base_quantity:,}".replace(",", " ") + f" {unit}"
    
    # Hent enheter sortert fra størst til minst
    units = list(product.units.filter(is_active=True).order_by('-conversion_factor'))
    
    if not units:
        return f"{base_quantity:,}".replace(",", " ") + f" {product.base_unit_type}"
    
    parts = []
    remaining = base_quantity
    
    for unit in units:
        if unit.conversion_factor <= remaining:
            whole, remaining = unit.from_base_units(remaining)
            if whole > 0:
                display_name = unit.short_name or unit.name
                parts.append(f"{whole} {display_name}")
    
    # Legg til rest i base-enheter hvis det er noe igjen
    if include_base_remainder and remaining > 0:
        parts.append(f"{remaining} {product.base_unit_type}")
    
    if not parts:
        return f"0 {product.base_unit_type}"
    
    return ", ".join(parts)


@transaction.atomic
def process_transaction(product, quantity: int, transaction_type: str,
                        event, unit_id: int = None, unit_name: str = None,
                        allow_negative: bool = False, user=None,
                        **extra_fields) -> 'StockTransaction':
    """
    Prosesser en lagertransaksjon med enhetskonvertering.
    
    Dette er hovedfunksjonen for alle lagerbevegelser. Den:
    1. Konverterer quantity til base-enheter
    2. Validerer at det er nok på lager (for uttak)
    3. Oppretter StockTransaction
    4. Oppdaterer StockLevel automatisk (via model save)
    
    Args:
        product: Product-objekt
        quantity: Antall i den valgte enheten (alltid positivt)
        transaction_type: Type transaksjon (RECEIVING, SALE, etc.)
        event: Event-objekt
        unit_id: ID til enhet (valgfritt)
        unit_name: Navn på enhet (valgfritt)
        allow_negative: Tillat negativ beholdning (default: False)
        user: Bruker som utfører transaksjonen
        **extra_fields: Andre felter for StockTransaction (notes, reference, etc.)
        
    Returns:
        StockTransaction-objekt
        
    Raises:
        UnitConversionError: Ved ugyldig enhet
        InsufficientStockError: Hvis det ikke er nok på lager
    """
    from .models import StockTransaction
    
    # Konverter til base-enheter
    if product.use_unit_conversion and (unit_id or unit_name):
        base_quantity = convert_to_base_units(product, quantity, unit_id, unit_name)
    else:
        base_quantity = quantity
    
    # Bestem fortegn basert på transaksjonstype
    # Positive = inn på lager, negative = ut av lager
    outgoing_types = [
        StockTransaction.TransactionType.SALE,
        StockTransaction.TransactionType.SHRINKAGE,
        StockTransaction.TransactionType.WASTE,
        StockTransaction.TransactionType.STAFF_CONSUMPTION,
        StockTransaction.TransactionType.TASTING,
        StockTransaction.TransactionType.RETURN,
    ]
    
    if transaction_type in outgoing_types:
        signed_quantity = -abs(base_quantity)
    else:
        signed_quantity = abs(base_quantity)
    
    # Valider beholdning for uttak
    if signed_quantity < 0 and not allow_negative:
        is_valid, current, new_stock = product.validate_stock_for_transaction(
            abs(signed_quantity), event
        )
        if not is_valid:
            unit_display = unit_name or product.base_unit_type
            raise InsufficientStockError(
                product=product,
                required=abs(signed_quantity),
                available=current,
                unit_name=unit_display
            )
    
    # Opprett transaksjon
    tx = StockTransaction.objects.create(
        product=product,
        event=event,
        transaction_type=transaction_type,
        quantity=signed_quantity,
        created_by=user,
        transaction_date=timezone.now(),
        **extra_fields
    )
    
    return tx


def process_receiving(product, quantity: int, event, unit_id: int = None,
                      unit_name: str = None, user=None, **extra_fields) -> 'StockTransaction':
    """
    Prosesser et varemottak.
    
    Convenience-funksjon for process_transaction med RECEIVING type.
    """
    from .models import StockTransaction
    return process_transaction(
        product=product,
        quantity=quantity,
        transaction_type=StockTransaction.TransactionType.RECEIVING,
        event=event,
        unit_id=unit_id,
        unit_name=unit_name,
        user=user,
        **extra_fields
    )


def process_sale(product, quantity: int, event, unit_id: int = None,
                 unit_name: str = None, allow_negative: bool = False,
                 user=None, **extra_fields) -> 'StockTransaction':
    """
    Prosesser et salg.
    
    Convenience-funksjon for process_transaction med SALE type.
    """
    from .models import StockTransaction
    return process_transaction(
        product=product,
        quantity=quantity,
        transaction_type=StockTransaction.TransactionType.SALE,
        event=event,
        unit_id=unit_id,
        unit_name=unit_name,
        allow_negative=allow_negative,
        user=user,
        **extra_fields
    )


def process_shrinkage(product, quantity: int, event, reason: str,
                      unit_id: int = None, unit_name: str = None,
                      allow_negative: bool = False, user=None,
                      **extra_fields) -> 'StockTransaction':
    """
    Prosesser svinnregistrering.
    
    Convenience-funksjon for process_transaction med SHRINKAGE type.
    """
    from .models import StockTransaction
    return process_transaction(
        product=product,
        quantity=quantity,
        transaction_type=StockTransaction.TransactionType.SHRINKAGE,
        event=event,
        unit_id=unit_id,
        unit_name=unit_name,
        allow_negative=allow_negative,
        user=user,
        reference=reason,
        **extra_fields
    )


def process_count_adjustment(product, counted_quantity: int, event,
                             unit_id: int = None, unit_name: str = None,
                             user=None, **extra_fields) -> Optional['StockTransaction']:
    """
    Prosesser en tellejustering.
    
    Beregner differanse mellom talt og forventet beholdning og oppretter
    en justeringstransaksjon.
    
    Args:
        product: Product-objekt
        counted_quantity: Talt antall i valgt enhet
        event: Event-objekt
        unit_id: Enhet-ID (valgfritt)
        unit_name: Enhetsnavn (valgfritt)
        user: Bruker
        
    Returns:
        StockTransaction hvis det er avvik, ellers None
    """
    from .models import StockTransaction
    
    # Konverter talt antall til base-enheter
    if product.use_unit_conversion and (unit_id or unit_name):
        counted_base = convert_to_base_units(product, counted_quantity, unit_id, unit_name)
    else:
        counted_base = counted_quantity
    
    # Hent nåværende beholdning
    current_stock = product.get_current_stock(event)
    
    # Beregn differanse
    difference = counted_base - current_stock
    
    if difference == 0:
        return None
    
    # Opprett justeringstransaksjon
    tx = StockTransaction.objects.create(
        product=product,
        event=event,
        transaction_type=StockTransaction.TransactionType.COUNT,
        quantity=difference,  # Positiv = mer enn forventet, negativ = mindre
        created_by=user,
        transaction_date=timezone.now(),
        notes=f"Tellejustering: Forventet {current_stock}, talt {counted_base} ({product.base_unit_type})",
        **extra_fields
    )
    
    return tx


def create_default_units_for_liquid(product, volume_ml: int = None) -> List['UnitOfMeasure']:
    """
    Opprett standard enheter for væskeprodukter.
    
    Oppretter typiske enheter for bar/restaurant:
    - Tank 30L (for fatøl)
    - Flaske (330ml, 500ml, 750ml)
    - Glass (0.3L, 0.4L, 0.5L)
    
    Args:
        product: Product-objekt med base_unit_type='ml'
        volume_ml: Standard flaskevolum (valgfritt)
        
    Returns:
        Liste med opprettede UnitOfMeasure-objekter
    """
    from .models import UnitOfMeasure
    
    if product.base_unit_type not in ('ml', 'cl'):
        raise UnitConversionError("Denne funksjonen er kun for væskeprodukter")
    
    units = []
    base_factor = 1 if product.base_unit_type == 'ml' else 10  # cl = 10ml
    
    # Standard enheter for fatøl
    standard_units = [
        # (name, short_name, factor_ml, is_purchase, is_sale, is_count, sort_order)
        ("Tank 30L", "Tank", 30000, True, False, True, 1),
        ("Fustage 20L", "20L", 20000, True, False, True, 2),
        ("Liter", "L", 1000, True, True, True, 10),
        ("Glass 0.5L", "0.5L", 500, False, True, True, 20),
        ("Glass 0.4L", "0.4L", 400, False, True, True, 21),
        ("Glass 0.3L", "0.3L", 300, False, True, True, 22),
    ]
    
    for name, short_name, factor_ml, is_purchase, is_sale, is_count, sort_order in standard_units:
        factor = factor_ml if product.base_unit_type == 'ml' else factor_ml // 10
        unit, created = UnitOfMeasure.objects.get_or_create(
            product=product,
            name=name,
            defaults={
                'short_name': short_name,
                'conversion_factor': factor,
                'is_purchase_unit': is_purchase,
                'is_sale_unit': is_sale,
                'is_count_unit': is_count,
                'sort_order': sort_order,
            }
        )
        if created:
            units.append(unit)
    
    return units


def create_default_units_for_bottles(product, bottle_ml: int = 750) -> List['UnitOfMeasure']:
    """
    Opprett standard enheter for flaske-produkter (vin, brennevin).
    
    Args:
        product: Product-objekt
        bottle_ml: Standard flaskevolum i ml (default 750ml for vin)
        
    Returns:
        Liste med opprettede UnitOfMeasure-objekter
    """
    from .models import UnitOfMeasure
    
    if product.base_unit_type not in ('ml', 'cl'):
        raise UnitConversionError("Denne funksjonen er kun for væskeprodukter")
    
    units = []
    
    bottle_factor = bottle_ml if product.base_unit_type == 'ml' else bottle_ml // 10
    
    standard_units = [
        # (name, short_name, factor, is_purchase, is_sale, is_count, sort_order)
        ("Kartong (6 fl)", "Krt", bottle_factor * 6, True, False, True, 1),
        ("Flaske", "Fl", bottle_factor, True, True, True, 10),
        ("Glass", "Glass", bottle_ml // 6, False, True, False, 20),  # Ca 125ml for vinglass
    ]
    
    for name, short_name, factor, is_purchase, is_sale, is_count, sort_order in standard_units:
        unit, created = UnitOfMeasure.objects.get_or_create(
            product=product,
            name=name,
            defaults={
                'short_name': short_name,
                'conversion_factor': factor,
                'is_purchase_unit': is_purchase,
                'is_sale_unit': is_sale,
                'is_count_unit': is_count,
                'sort_order': sort_order,
            }
        )
        if created:
            units.append(unit)
    
    return units


def get_stock_summary(product, event=None) -> Dict:
    """
    Hent komplett lageroppsummering for et produkt.
    
    Returns:
        dict med:
        - base_quantity: Antall i base-enheter
        - base_unit: Base-enhetstype (ml, stk, etc.)
        - formatted: Human-readable streng
        - by_unit: Liste med antall per enhet
    """
    base_qty = product.get_current_stock(event)
    
    result = {
        'base_quantity': base_qty,
        'base_unit': product.base_unit_type,
        'formatted': format_stock_display(product, base_qty),
        'by_unit': [],
    }
    
    if product.use_unit_conversion:
        remaining = base_qty
        for unit in product.units.filter(is_active=True).order_by('-conversion_factor'):
            whole, remaining = unit.from_base_units(remaining)
            result['by_unit'].append({
                'unit_id': unit.id,
                'unit_name': unit.name,
                'short_name': unit.short_name,
                'quantity': whole,
                'conversion_factor': unit.conversion_factor,
            })
        
        # Legg til rest
        if remaining > 0:
            result['by_unit'].append({
                'unit_id': None,
                'unit_name': product.base_unit_type,
                'short_name': product.base_unit_type,
                'quantity': remaining,
                'conversion_factor': 1,
            })
    
    return result
