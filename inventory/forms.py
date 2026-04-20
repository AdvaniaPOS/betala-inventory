"""
Forms for lagersystemet.
"""

from decimal import Decimal
from django import forms
from django.utils import timezone
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Submit, Row, Column, Fieldset, HTML, Div

from .models import (
    Product, StockTransaction, ReceivingOrder, ReceivingOrderLine,
    ShrinkageEntry, StockCount, StockCountLine, Event, Supplier,
    PurchaseOrder, PurchaseOrderLine
)


class ProductFilterForm(forms.Form):
    """Filtrering av produkter."""
    search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'placeholder': 'Søk etter navn, SKU eller strekkode...',
            'class': 'form-control'
        })
    )
    category = forms.ChoiceField(
        required=False,
        choices=[('', 'Alle kategorier')]
    )
    show_inactive = forms.BooleanField(required=False, label='Vis inaktive')
    
    def __init__(self, *args, categories=None, **kwargs):
        super().__init__(*args, **kwargs)
        if categories:
            self.fields['category'].choices = [('', 'Alle kategorier')] + [
                (c.id, c.name) for c in categories
            ]


class StockTransactionForm(forms.ModelForm):
    """Skjema for å opprette lagertransaksjoner manuelt."""
    
    class Meta:
        model = StockTransaction
        fields = ['product', 'event', 'transaction_type', 'quantity', 
                  'unit_cost_ore', 'reference', 'notes', 'location', 'supplier']
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.layout = Layout(
            Row(
                Column('product', css_class='col-md-6'),
                Column('event', css_class='col-md-6'),
            ),
            Row(
                Column('transaction_type', css_class='col-md-4'),
                Column('quantity', css_class='col-md-4'),
                Column('unit_cost_ore', css_class='col-md-4'),
            ),
            Row(
                Column('location', css_class='col-md-6'),
                Column('supplier', css_class='col-md-6'),
            ),
            'reference',
            'notes',
            Submit('submit', 'Lagre', css_class='btn-primary')
        )


class ReceivingOrderForm(forms.ModelForm):
    """Skjema for varemottak."""
    
    class Meta:
        model = ReceivingOrder
        fields = ['event', 'supplier', 'order_number', 'delivery_note', 
                  'received_date', 'notes']
        widgets = {
            'received_date': forms.DateInput(attrs={'type': 'date'}),
            'notes': forms.Textarea(attrs={'rows': 3}),
        }
    
    def __init__(self, *args, organization_id=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Filtrer events på organisasjon
        if organization_id:
            self.fields['event'].queryset = Event.objects.filter(
                is_active=True,
                betala_organization_id=organization_id
            )
        else:
            self.fields['event'].queryset = Event.objects.filter(is_active=True)
        # Sett default mottaksdato til i dag
        if not self.instance.pk:
            self.fields['received_date'].initial = timezone.now().date()
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.layout = Layout(
            Row(
                Column('event', css_class='col-md-6'),
                Column('supplier', css_class='col-md-6'),
            ),
            Row(
                Column('order_number', css_class='col-md-4'),
                Column('delivery_note', css_class='col-md-4'),
                Column('received_date', css_class='col-md-4'),
            ),
            'notes',
            Submit('submit', 'Opprett varemottak', css_class='btn-primary')
        )


class ReceivingOrderLineForm(forms.ModelForm):
    """Skjema for en linje i varemottak."""
    
    # Bruk desimalfelt for kr i stedet for øre
    unit_cost_kr = forms.DecimalField(
        label='Enhetskost (kr)',
        max_digits=10,
        decimal_places=2,
        required=False,  # Gjør valgfritt, sjekk i clean()
        min_value=Decimal('0'),
        widget=forms.NumberInput(attrs={
            'step': '0.01',
            'placeholder': '0,00',
            'class': 'form-control'
        })
    )
    
    class Meta:
        model = ReceivingOrderLine
        fields = ['product', 'quantity_expected', 'quantity_received',
                  'batch_number', 'expiry_date', 'notes']
        widgets = {
            'expiry_date': forms.DateInput(attrs={'type': 'date'}),
        }
    
    def __init__(self, *args, organization_id=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Filtrer produkter på organisasjon
        if organization_id:
            self.fields['product'].queryset = Product.objects.filter(
                is_active=True,
                betala_organization_id=organization_id
            ).exclude(betala_is_bundles=True).order_by('name')
        else:
            self.fields['product'].queryset = Product.objects.filter(
                is_active=True
            ).exclude(betala_is_bundles=True).order_by('name')
        # Konverter øre til kr ved visning
        if self.instance and self.instance.pk and self.instance.unit_cost_ore:
            self.fields['unit_cost_kr'].initial = self.instance.unit_cost_ore / 100
        # Gjør quantity_received valgfritt (settes til 0 hvis tom)
        self.fields['quantity_received'].required = False
    
    def clean(self):
        cleaned_data = super().clean()
        product = cleaned_data.get('product')
        quantity_received = cleaned_data.get('quantity_received')
        unit_cost_kr = cleaned_data.get('unit_cost_kr')
        
        # Hvis et produkt er valgt, kreves mottatt antall og enhetspris
        if product:
            if not quantity_received and quantity_received != 0:
                cleaned_data['quantity_received'] = 0
            if unit_cost_kr is None:
                self.add_error('unit_cost_kr', 'Enhetskost er påkrevd når produkt er valgt')
        
        return cleaned_data
    
    def save(self, commit=True):
        instance = super().save(commit=False)
        # Konverter kr til øre ved lagring
        unit_cost_kr = self.cleaned_data.get('unit_cost_kr')
        if unit_cost_kr is not None:
            instance.unit_cost_ore = int(unit_cost_kr * 100)
        else:
            instance.unit_cost_ore = 0
        if commit:
            instance.save()
        return instance


ReceivingOrderLineFormSet = forms.inlineformset_factory(
    ReceivingOrder,
    ReceivingOrderLine,
    form=ReceivingOrderLineForm,
    extra=3,
    can_delete=True
)


def get_receiving_line_formset(organization_id=None, *args, **kwargs):
    """Hjelpefunksjon for å opprette formset med organisasjonsfiltrering."""
    formset = ReceivingOrderLineFormSet(*args, **kwargs)
    # Sett produkt-queryset på alle forms i formset
    product_qs = Product.objects.filter(is_active=True)
    if organization_id:
        product_qs = product_qs.filter(betala_organization_id=organization_id)
    product_qs = product_qs.exclude(betala_is_bundles=True).order_by('name')
    
    for form in formset.forms:
        form.fields['product'].queryset = product_qs
    return formset


class ShrinkageEntryForm(forms.ModelForm):
    """Skjema for svinnregistrering."""
    
    class Meta:
        model = ShrinkageEntry
        fields = ['product', 'event', 'quantity', 'reason', 'location', 'notes']
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 2, 'placeholder': 'Beskriv svinn...'}),
        }
    
    def __init__(self, *args, organization_id=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Filtrer events og produkter på organisasjon
        if organization_id:
            self.fields['event'].queryset = Event.objects.filter(
                is_active=True,
                betala_organization_id=organization_id
            )
            self.fields['product'].queryset = Product.objects.filter(
                is_active=True,
                betala_organization_id=organization_id
            ).exclude(betala_is_bundles=True).order_by('name')
        else:
            self.fields['product'].queryset = Product.objects.filter(
                is_active=True
            ).exclude(betala_is_bundles=True).order_by('name')
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.layout = Layout(
            Row(
                Column('product', css_class='col-md-6'),
                Column('event', css_class='col-md-6'),
            ),
            Row(
                Column('quantity', css_class='col-md-4'),
                Column('reason', css_class='col-md-4'),
                Column('location', css_class='col-md-4'),
            ),
            'notes',
            Submit('submit', 'Registrer svinn', css_class='btn-warning')
        )


class QuickShrinkageForm(forms.Form):
    """Rask svinnregistrering med strekkodeskanner."""
    barcode = forms.CharField(
        label='Strekkode',
        widget=forms.TextInput(attrs={
            'placeholder': 'Skann eller skriv strekkode...',
            'autofocus': True
        })
    )
    quantity = forms.IntegerField(
        label='Antall',
        initial=1,
        min_value=1
    )
    reason = forms.ChoiceField(
        label='Årsak',
        choices=ShrinkageEntry.ShrinkageReason.choices
    )


class StockCountForm(forms.ModelForm):
    """Skjema for å starte varetelling."""
    
    class Meta:
        model = StockCount
        fields = ['event', 'name', 'location', 'notes']
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 2}),
        }
    
    def __init__(self, *args, organization_id=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Filtrer events på organisasjon
        if organization_id:
            self.fields['event'].queryset = Event.objects.filter(
                is_active=True,
                betala_organization_id=organization_id
            )
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.layout = Layout(
            Row(
                Column('event', css_class='col-md-6'),
                Column('name', css_class='col-md-6'),
            ),
            'location',
            'notes',
            Submit('submit', 'Start varetelling', css_class='btn-primary')
        )


class StockCountLineForm(forms.ModelForm):
    """Skjema for en tellelinje."""
    
    class Meta:
        model = StockCountLine
        fields = ['counted_quantity', 'notes']
        widgets = {
            'counted_quantity': forms.NumberInput(attrs={
                'class': 'form-control form-control-lg text-center',
                'style': 'max-width: 120px;'
            }),
            'notes': forms.TextInput(attrs={'placeholder': 'Merknad'}),
        }


class EventSelectForm(forms.Form):
    """Skjema for å velge aktivt event."""
    event = forms.ModelChoiceField(
        queryset=Event.objects.filter(is_active=True),
        label='Velg event',
        empty_label='-- Velg event --'
    )
    
    def __init__(self, *args, organization_id=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Filtrer events på organisasjon
        if organization_id:
            self.fields['event'].queryset = Event.objects.filter(
                is_active=True,
                betala_organization_id=organization_id
            )


# =============================================================================
# INNKJØPSORDRE SKJEMAER
# =============================================================================

class PurchaseOrderForm(forms.ModelForm):
    """Skjema for innkjøpsordre."""
    
    class Meta:
        model = PurchaseOrder
        fields = ['event', 'supplier', 'order_number', 'supplier_reference', 
                  'order_date', 'expected_delivery', 'notes']
        widgets = {
            'event': forms.Select(attrs={'class': 'form-select'}),
            'supplier': forms.Select(attrs={'class': 'form-select'}),
            'order_number': forms.TextInput(attrs={'class': 'form-control'}),
            'supplier_reference': forms.TextInput(attrs={'class': 'form-control'}),
            'order_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'expected_delivery': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
        }
    
    def __init__(self, *args, organization_id=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Filtrer events på organisasjon
        if organization_id:
            self.fields['event'].queryset = Event.objects.filter(
                is_active=True,
                betala_organization_id=organization_id
            )
        self.fields['order_number'].required = False
        self.fields['order_number'].help_text = 'Genereres automatisk hvis tomt'


class PurchaseOrderLineForm(forms.ModelForm):
    """Skjema for en linje i innkjøpsordre."""
    
    # Bruk desimalfelt for kr i stedet for øre
    unit_cost_kr = forms.DecimalField(
        label='Enhetskost (kr)',
        max_digits=10,
        decimal_places=2,
        required=False,  # Valideres i clean() når produkt er valgt
        min_value=0,
        widget=forms.NumberInput(attrs={
            'step': '0.01',
            'placeholder': '0,00',
            'class': 'form-control'
        })
    )
    
    class Meta:
        model = PurchaseOrderLine
        fields = ['product', 'quantity_ordered', 'notes']
        widgets = {
            'product': forms.Select(attrs={'class': 'form-select'}),
            'quantity_ordered': forms.NumberInput(attrs={'class': 'form-control', 'min': '1', 'placeholder': '0'}),
            'notes': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Valgfritt'}),
        }
    
    def __init__(self, *args, organization_id=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Gjør quantity_ordered valgfritt - valideres i clean()
        self.fields['quantity_ordered'].required = False
        # Konverter øre til kr ved visning
        if self.instance and self.instance.pk and self.instance.unit_cost_ore:
            self.fields['unit_cost_kr'].initial = self.instance.unit_cost_ore / 100
        # Filtrer produkter på organisasjon
        if organization_id:
            self.fields['product'].queryset = Product.objects.filter(
                is_active=True,
                betala_organization_id=organization_id
            ).exclude(betala_is_bundles=True).order_by('name')
        else:
            self.fields['product'].queryset = Product.objects.filter(
                is_active=True
            ).exclude(betala_is_bundles=True).order_by('name')
    
    def clean(self):
        cleaned_data = super().clean()
        product = cleaned_data.get('product')
        unit_cost_kr = cleaned_data.get('unit_cost_kr')
        quantity_ordered = cleaned_data.get('quantity_ordered')
        
        # Hvis et produkt er valgt, kreves antall og enhetspris
        if product:
            if not quantity_ordered or quantity_ordered < 1:
                self.add_error('quantity_ordered', 'Antall er påkrevd når produkt er valgt')
            if unit_cost_kr is None:
                self.add_error('unit_cost_kr', 'Enhetskost er påkrevd når produkt er valgt')
        
        return cleaned_data
    
    def save(self, commit=True):
        instance = super().save(commit=False)
        # Konverter kr til øre ved lagring
        unit_cost_kr = self.cleaned_data.get('unit_cost_kr')
        if unit_cost_kr is not None:
            instance.unit_cost_ore = int(unit_cost_kr * 100)
        if commit:
            instance.save()
        return instance


PurchaseOrderLineFormSet = forms.inlineformset_factory(
    PurchaseOrder,
    PurchaseOrderLine,
    form=PurchaseOrderLineForm,
    extra=5,
    can_delete=True
)


def get_purchase_order_line_formset(organization_id=None, *args, **kwargs):
    """Hjelpefunksjon for å opprette formset med organisasjonsfiltrering."""
    formset = PurchaseOrderLineFormSet(*args, **kwargs)
    # Sett produkt-queryset på alle forms i formset
    product_qs = Product.objects.filter(is_active=True)
    if organization_id:
        product_qs = product_qs.filter(betala_organization_id=organization_id)
    product_qs = product_qs.exclude(betala_is_bundles=True).order_by('name')
    
    for form in formset.forms:
        form.fields['product'].queryset = product_qs
    return formset


class ReceiveFromPurchaseOrderForm(forms.Form):
    """Skjema for å motta varer fra innkjøpsordre."""
    delivery_note = forms.CharField(
        label='Følgeseddel',
        max_length=100,
        required=False
    )
    received_date = forms.DateField(
        label='Mottaksdato',
        widget=forms.DateInput(attrs={'type': 'date'}),
        initial=timezone.now
    )
    notes = forms.CharField(
        label='Notater',
        widget=forms.Textarea(attrs={'rows': 2}),
        required=False
    )
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.layout = Layout(
            'event',
            Submit('submit', 'Velg', css_class='btn-primary')
        )


# =============================================================================
# PRODUKT REDIGERING
# =============================================================================

class ProductEditForm(forms.ModelForm):
    """Skjema for å redigere produkt (synkroniseres til Betala ved lagring)."""
    
    # Pris i kr for brukergrensesnitt
    price_with_vat_kr = forms.DecimalField(
        label='Salgspris inkl. mva (kr)',
        max_digits=10,
        decimal_places=2,
        required=False,  # Ikke påkrevd ved åpen pris
        min_value=Decimal('0'),
        widget=forms.NumberInput(attrs={
            'step': '0.01',
            'placeholder': '0,00',
            'class': 'form-control',
            'id': 'id_price_with_vat_kr'
        })
    )
    
    # MVA-sats valg (vanlige norske satser)
    VAT_CHOICES = [
        (2500, '25% (standard)'),
        (1500, '15% (mat)'),
        (1200, '12% (transport)'),
        (0, '0% (fritak)'),
    ]
    vat_rate = forms.ChoiceField(
        label='MVA-sats',
        choices=VAT_CHOICES,
        initial=1500,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    
    # Tag (farge) valg - 0-11 i Betala
    TAG_CHOICES = [
        (0, '🔵 Lyseblå'),
        (1, '🔴 Rød/rosa'),
        (2, '🔵 Mørkeblå'),
        (3, '🟢 Mintgrønn'),
        (4, '🔵 Teal'),
        (5, '🟣 Lilla'),
        (6, '🟠 Oransje'),
        (7, '🔵 Blålilla'),
        (8, '⚫ Grå'),
        (9, '💗 Rosa'),
        (10, '⬛ Svart'),
        (11, '🟢 Limegrønn'),
    ]
    betala_tag = forms.ChoiceField(
        label='Produktfarge',
        choices=TAG_CHOICES,
        initial=0,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    
    # Artikkelgruppe dropdown
    ARTICLE_GROUP_CHOICES = [
        ('04001', '04001 - Uttak av behandlingstjenester'),
        ('04002', '04002 - Uttak av behandlingsvarer'),
        ('04003', '04003 - Varesalg'),
        ('04004', '04004 - Salg av behandlingstjenester'),
        ('04005', '04005 - Salg av hårklipp'),
        ('04006', '04006 - Mat'),
        ('04007', '04007 - Øl'),
        ('04008', '04008 - Vin'),
        ('04009', '04009 - Brennevin'),
        ('04010', '04010 - Rusbrus/Cider'),
        ('04011', '04011 - Mineralvann (brus)'),
        ('04012', '04012 - Annen drikke (te, kaffe etc)'),
        ('04013', '04013 - Tobakk'),
        ('04014', '04014 - Andre varer'),
        ('04015', '04015 - Inngangspenger'),
        ('04016', '04016 - Inngangspenger fri adgang'),
        ('04017', '04017 - Garderobeavgift'),
        ('04018', '04018 - Garderobeavgift fri'),
        ('04019', '04019 - Helpensjon'),
        ('04020', '04020 - Halvpensjon'),
        ('04021', '04021 - Overnatting med frokost'),
        ('04999', '04999 - Øvrige'),
    ]
    betala_article_group_id = forms.ChoiceField(
        label='Artikkelgruppe',
        choices=ARTICLE_GROUP_CHOICES,
        initial='04999',
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    
    class Meta:
        model = Product
        fields = [
            'name', 'description', 'category_name', 
            'betala_article_group_id', 'betala_open_price',
            'betala_is_bar_printing', 'betala_is_kitchen_printing', 
            'betala_general_ledger_account',
            'supplier', 'purchase_price_ore', 'min_stock_level',
            'barcode',
        ]
        widgets = {
            'description': forms.Textarea(attrs={'rows': 2}),
            'barcode': forms.TextInput(attrs={'placeholder': 'EAN-13, UPC, etc.', 'class': 'form-control'}),
        }
        labels = {
            'category_name': 'Kategori',
            'betala_open_price': 'Åpen pris',
            'betala_is_bar_printing': 'Skriv ut på bar',
            'betala_is_kitchen_printing': 'Skriv ut på kjøkken',
            'betala_general_ledger_account': 'Hovedbokskonto',
            'supplier': 'Leverandør',
            'purchase_price_ore': 'Innkjøpspris (øre)',
            'min_stock_level': 'Min. lagerbeholdning',
            'barcode': 'Strekkode',
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        is_bundle = False
        
        # Sett startverdier hvis vi redigerer et eksisterende produkt
        if self.instance and self.instance.pk:
            is_bundle = self.instance.betala_is_bundles
            
            # Konverter øre til kr
            if self.instance.price_with_vat_ore:
                self.fields['price_with_vat_kr'].initial = Decimal(
                    self.instance.price_with_vat_ore
                ) / 100
            # Sett MVA-sats (kun for vanlige produkter, pakker har ikke egen MVA)
            if self.instance.vat_factor and not is_bundle:
                # Konverter til nærmeste standardverdi hvis nødvendig
                vat_val = self.instance.vat_factor
                standard_vat_values = [2500, 1500, 1200, 0]
                if vat_val not in standard_vat_values:
                    # Rund til nærmeste standardverdi
                    if vat_val > 2000:
                        vat_val = 2500
                    elif vat_val > 1350:
                        vat_val = 1500
                    elif vat_val > 600:
                        vat_val = 1200
                    else:
                        vat_val = 0
                self.fields['vat_rate'].initial = str(vat_val)
            # Sett tag (farge)
            self.fields['betala_tag'].initial = str(self.instance.betala_tag or 0)
            # Sett artikkelgruppe
            if self.instance.betala_article_group_id:
                self.fields['betala_article_group_id'].initial = self.instance.betala_article_group_id
        
        # Hvis pakke, deaktiver prisfelter og innkjøpsfelt
        if is_bundle:
            self.fields['price_with_vat_kr'].disabled = True
            self.fields['price_with_vat_kr'].help_text = 'Pris beregnes automatisk fra pakke-innholdet'
            # Pakker har ikke egen MVA - kassen beregner MVA fra produktene i pakken
            self.fields['vat_rate'].widget = forms.HiddenInput()
            self.fields['vat_rate'].required = False
            self.fields['betala_open_price'].disabled = True
            self.fields['purchase_price_ore'].disabled = True
            self.fields['purchase_price_ore'].help_text = 'Innkjøp skjer på enkeltproduktene i pakken'
            self.fields['min_stock_level'].disabled = True
            self.fields['min_stock_level'].help_text = 'Lagerbeholdning spores på enkeltproduktene'
        
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        
        # Bygg layout - med eller uten prisseksjon basert på om det er pakke
        if is_bundle:
            self.helper.layout = Layout(
                Fieldset(
                    'Produktinformasjon',
                    'name',
                    'description',
                    Row(
                        Column('category_name', css_class='col-md-6'),
                        Column('betala_article_group_id', css_class='col-md-6'),
                    ),
                ),
                Fieldset(
                    'Pakke-prising (beregnes automatisk)',
                    HTML('''
                        <div class="alert alert-info mb-3">
                            <i class="bi bi-info-circle"></i>
                            <strong>Pakke-pris:</strong> Prisen beregnes automatisk fra innholdet i pakken.
                            <a href="{% url 'inventory:bundle_edit' form.instance.betala_product_id %}" class="alert-link">
                                Rediger pakke-innhold →
                            </a>
                        </div>
                    '''),
                    Row(
                        Column('price_with_vat_kr', css_class='col-md-4'),
                        Column('vat_rate', css_class='col-md-4'),
                    ),
                ),
                Fieldset(
                    'Betala-innstillinger',
                    Row(
                        Column('betala_tag', css_class='col-md-4'),
                        Column('betala_is_bar_printing', css_class='col-md-4'),
                        Column('betala_is_kitchen_printing', css_class='col-md-4'),
                    ),
                    Row(
                        Column('betala_general_ledger_account', css_class='col-md-6'),
                    ),
                ),
                Fieldset(
                    'Identifikasjon',
                    Row(
                        Column('barcode', css_class='col-md-6'),
                    ),
                ),
                Div(
                    Submit('submit', 'Lagre og synkroniser til Betala', 
                           css_class='btn-primary'),
                    HTML('<a href="{% url \'inventory:product_detail\' form.instance.betala_product_id %}" '
                         'class="btn btn-secondary ms-2">Avbryt</a>'),
                    css_class='mt-4'
                )
            )
        else:
            self.helper.layout = Layout(
                Fieldset(
                    'Produktinformasjon',
                    'name',
                    'description',
                    Row(
                        Column('category_name', css_class='col-md-6'),
                        Column('betala_article_group_id', css_class='col-md-6'),
                    ),
                ),
                Fieldset(
                    'Prising',
                    Row(
                    Column('price_with_vat_kr', css_class='col-md-4'),
                    Column('vat_rate', css_class='col-md-4'),
                    Column('betala_open_price', css_class='col-md-4'),
                ),
            ),
            Fieldset(
                'Betala-innstillinger',
                Row(
                    Column('betala_tag', css_class='col-md-4'),
                    Column('betala_is_bar_printing', css_class='col-md-4'),
                    Column('betala_is_kitchen_printing', css_class='col-md-4'),
                ),
                Row(
                    Column('betala_general_ledger_account', css_class='col-md-6'),
                ),
            ),
            Fieldset(
                'Lager og innkjøp',
                Row(
                    Column('supplier', css_class='col-md-6'),
                    Column('purchase_price_ore', css_class='col-md-3'),
                    Column('min_stock_level', css_class='col-md-3'),
                ),
                Row(
                    Column('barcode', css_class='col-md-6'),
                ),
            ),
            Div(
                Submit('submit', 'Lagre og synkroniser til Betala', 
                       css_class='btn-primary'),
                HTML('<a href="{% url \'inventory:product_detail\' form.instance.betala_product_id %}" '
                     'class="btn btn-secondary ms-2">Avbryt</a>'),
                css_class='mt-4'
            )
        )
    
    def clean(self):
        cleaned_data = super().clean()
        open_price = cleaned_data.get('betala_open_price')
        price_with_vat_kr = cleaned_data.get('price_with_vat_kr')
        
        # Hvis ikke åpen pris, må det være en pris
        if not open_price and not price_with_vat_kr:
            self.add_error('price_with_vat_kr', 'Pris er påkrevd når "Åpen pris" ikke er valgt')
        
        return cleaned_data
    
    def save(self, commit=True):
        instance = super().save(commit=False)
        
        # Sjekk om åpen pris
        if instance.betala_open_price:
            # Ved åpen pris: sett pris og mva til None
            instance.price_ore = None
            instance.vat_ore = None
        else:
            # Konverter pris til øre og beregn mva
            price_with_vat_kr = self.cleaned_data.get('price_with_vat_kr')
            vat_factor = int(self.cleaned_data.get('vat_rate'))
            
            if price_with_vat_kr is not None:
                # Pris inkl. mva i øre (dette er det vi sender til Betala)
                price_with_vat_ore = round(price_with_vat_kr * 100)
                
                # Beregn pris eks. mva og mva-beløp
                # vat_factor er f.eks. 1500 for 15%, 2500 for 25%
                vat_rate_decimal = Decimal(vat_factor) / 10000  # 1500 -> 0.15
                
                # Pris eks. mva = pris inkl. mva / (1 + mva-sats)
                price_eks_mva_ore = round(price_with_vat_ore / (1 + vat_rate_decimal))
                # MVA = totalpris - pris eks. mva (slik at summen alltid blir korrekt)
                vat_ore = price_with_vat_ore - price_eks_mva_ore
                
                instance.price_ore = int(price_eks_mva_ore)
                instance.vat_ore = int(vat_ore)
        
        # Lagre MVA-sats (kun for vanlige produkter, ikke pakker)
        if not instance.betala_is_bundles:
            vat_rate = self.cleaned_data.get('vat_rate')
            if vat_rate:
                instance.vat_factor = int(vat_rate)
        
        # Lagre tag (farge)
        betala_tag = self.cleaned_data.get('betala_tag')
        if betala_tag is not None:
            instance.betala_tag = int(betala_tag)
        
        # Lagre strekkode eksplisitt (lokalt felt, ikke synket til Betala)
        barcode = self.cleaned_data.get('barcode')
        if barcode is not None:
            instance.barcode = barcode
        
        if commit:
            instance.save()
            # Merk: Pakke-oppdatering håndteres i view etter Betala-synk
        
        return instance


# =============================================================================
# PAKKE-REDIGERING
# =============================================================================

class BundleItemForm(forms.Form):
    """Skjema for et enkelt produkt i en pakke."""
    product_id = forms.IntegerField(widget=forms.HiddenInput())
    product_name = forms.CharField(
        disabled=True, 
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control-plaintext'})
    )
    quantity = forms.IntegerField(
        min_value=0,
        widget=forms.NumberInput(attrs={
            'class': 'form-control text-center',
            'style': 'width: 80px;'
        })
    )


class BundleContentsForm(forms.Form):
    """Skjema for å redigere pakke-innhold."""
    
    def __init__(self, *args, bundle=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.bundle = bundle
        
        if bundle:
            # Hent eksisterende innhold
            contents = bundle.get_bundle_contents()
            
            # Legg til felt for hvert produkt i pakken
            for product_id, quantity in contents.items():
                product = Product.objects.filter(betala_product_id=product_id).first()
                if product:
                    field_name = f'qty_{product_id}'
                    self.fields[field_name] = forms.IntegerField(
                        label=product.name,
                        initial=quantity,
                        min_value=0,
                        widget=forms.NumberInput(attrs={
                            'class': 'form-control text-center',
                            'style': 'width: 100px;',
                            'data-product-id': product_id,
                            'data-price': product.price_with_vat_ore or 0,
                        })
                    )
    
    def save(self):
        """Lagre endringer til pakken."""
        if not self.bundle:
            return
        
        contents = {}
        for field_name, value in self.cleaned_data.items():
            if field_name.startswith('qty_'):
                product_id = int(field_name.replace('qty_', ''))
                if value > 0:
                    contents[product_id] = value
        
        self.bundle.set_bundle_contents(contents)
        self.bundle.save()
        
        return self.bundle


class AddBundleItemForm(forms.Form):
    """Skjema for å legge til produkt i pakke."""
    product = forms.ModelChoiceField(
        queryset=Product.objects.filter(
            is_active=True,
            betala_is_bundles=False  # Ikke tillat pakker i pakker
        ).order_by('name'),
        label='Produkt',
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    quantity = forms.IntegerField(
        label='Antall',
        initial=1,
        min_value=1,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'style': 'width: 100px;'
        })
    )
    
    def __init__(self, *args, organization_id=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Filtrer produkter basert på organisasjon
        queryset = Product.objects.filter(
            is_active=True,
            betala_is_bundles=False
        )
        if organization_id:
            queryset = queryset.filter(betala_organization_id=organization_id)
        self.fields['product'].queryset = queryset.order_by('name')
