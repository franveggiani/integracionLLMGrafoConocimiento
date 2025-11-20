"""
Clasificador de movimientos financieros.

Se reutiliza el dataset sintético de categorías y se entrena un modelo
LogisticRegression sobre una representación TF-IDF. El objetivo es exponer
una API muy simple para que otros componentes (LangChain/agents) puedan
invocar `categorize_movement` y obtener la categoría estimada del movimiento.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import List, Tuple

import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression


def _replicate_samples(base: List[str], n: int, rng: random.Random) -> List[str]:
    """
    Genera n ejemplos pseudoaleatorios agregando un sufijo para darles
    mayor diversidad textual. Mantiene determinismo si se fija la seed.
    """
    return [f"{rng.choice(base)} #{i}" for i in range(1, n + 1)]


def _build_dataset(random_state: int = 42) -> Tuple[List[str], List[str]]:
    rng = random.Random(random_state)

    categorias_base = {
        "Alimentación": [
            "café en Starbucks", "almuerzo en McDonalds", "compra en supermercado",
            "cena en restaurante", "pedido por PedidosYa", "compra en verdulería",
            "panadería local", "compra de frutas", "cena con amigos",
            "hamburguesa", "gaseosa", "snacks", "delivery", "pizza", "helado",
            "cerveza artesanal", "bebidas en kiosco", "almuerzo trabajo",
            "desayuno bar", "compras en dietética",
        ],
        "Transporte": [
            "boleto de colectivo", "viaje en taxi", "Uber a casa", "nafta para el auto",
            "mantenimiento del auto", "peaje", "pasaje de tren", "pasaje de micro",
            "bicicleta compartida", "estacionamiento", "combustible", "subte",
            "taxi aeropuerto", "remis", "lavado de auto", "aceite motor",
            "revisión técnica", "recarga SUBE", "alquiler de monopatín", "autopista",
        ],
        "Entretenimiento": [
            "entrada de cine", "Netflix mensual", "Spotify suscripción", "juego en Steam",
            "salida al teatro", "compra de videojuego", "suscripción Disney+",
            "YouTube Premium", "fiesta de amigos", "salida nocturna", "bar karaoke",
            "concierto", "boletos recital", "evento deportivo", "casino online",
            "app de meditación", "película digital", "libro de ficción",
            "paseo en parque", "suscripción HBO",
        ],
        "Servicios": [
            "factura de luz", "pago de gas", "abono de internet", "teléfono celular",
            "expensas", "servicio de limpieza", "agua potable", "mantenimiento del hogar",
            "seguro del auto", "seguro de hogar", "hosting web", "dominio web",
            "Netflix familiar", "Spotify familiar", "reparación cañerías", "plomero",
            "electricista", "cuota de seguro", "servicio de vigilancia",
            "streaming mensual",
        ],
        "Educación": [
            "curso online de Python", "clases de inglés", "libro de programación",
            "suscripción Coursera", "seminario virtual", "charla técnica",
            "examen universitario", "material de estudio", "compra de cuadernos",
            "pago de matrícula", "taller de arte", "curso de cocina",
            "curso de marketing", "webinar", "licencia software educativo",
            "suscripción a Udemy", "curso de React", "clases particulares",
            "educación a distancia", "libro académico",
        ],
        "Salud": [
            "consulta médica", "compra de medicamentos", "turno odontológico",
            "gimnasio mensual", "análisis clínicos", "visita al oftalmólogo",
            "farmacia", "pago de obra social", "masaje relajante",
            "terapia psicológica", "clínica privada", "examen médico",
            "hospital privado", "suplementos vitamínicos",
            "tratamiento kinesiología", "urgencias médicas", "pago de mutual",
            "control de rutina", "dentista", "consultorio dermatológico",
        ],
    }

    descripciones: List[str] = []
    etiquetas: List[str] = []

    for categoria, textos in categorias_base.items():
        sinteticos = _replicate_samples(textos, n=100, rng=rng)
        descripciones.extend(sinteticos)
        etiquetas.extend([categoria] * len(sinteticos))

    df = pd.DataFrame({"descripcion": descripciones, "categoria": etiquetas})
    df = df.sample(frac=1, random_state=random_state).reset_index(drop=True)
    return df["descripcion"].tolist(), df["categoria"].tolist()


@dataclass
class MovementCategorizer:
    """
    Encapsula vectorizador + modelo. Se entrena al inicializar.
    """

    random_state: int = 42
    vectorizer: TfidfVectorizer | None = None
    model: LogisticRegression | None = None

    def __post_init__(self):
        self._train()

    def _train(self) -> None:
        X_texts, y = _build_dataset(self.random_state)
        self.vectorizer = TfidfVectorizer(stop_words=["spanish"])
        X = self.vectorizer.fit_transform(X_texts)
        self.model = LogisticRegression(max_iter=1000)
        self.model.fit(X, y)

    def predict(self, descripcion: str) -> str:
        if not descripcion or not descripcion.strip():
            raise ValueError("La descripción del movimiento no puede estar vacía.")
        if self.vectorizer is None or self.model is None:
            raise RuntimeError("El modelo aún no fue entrenado.")
        X = self.vectorizer.transform([descripcion])
        pred = self.model.predict(X)
        return pred[0]


# Instancia global reutilizable
_GLOBAL_CATEGORIZER: MovementCategorizer | None = None


def get_movement_categorizer() -> MovementCategorizer:
    global _GLOBAL_CATEGORIZER
    if _GLOBAL_CATEGORIZER is None:
        _GLOBAL_CATEGORIZER = MovementCategorizer()
    return _GLOBAL_CATEGORIZER


def categorize_movement(descripcion: str) -> str:
    """
    API pública. Devuelve la categoría estimada para la descripción dada.
    """
    categorizer = get_movement_categorizer()
    return categorizer.predict(descripcion)


if __name__ == "__main__":
    print("Clasificador de movimientos AFPI. Escribí la descripción o Ctrl+C para salir.\n")
    cat = get_movement_categorizer()
    try:
        while True:
            texto = input("Descripción> ").strip()
            if not texto:
                continue
            categoria = cat.predict(texto)
            print(f"Categoría estimada: {categoria}\n")
    except KeyboardInterrupt:
        print("\nHasta luego.")
