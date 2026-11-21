from .config import Settings
from .engine import load_engine
from .pantry import Pantry
from .api.server import make_server


def main():
    s = Settings()
    engine = load_engine(s.engine)
    pantry = Pantry(engine, s.data_dir / "pantry.json", s.chunk_words, s.chunk_overlap)
    server = make_server(s, engine, pantry)
    print(f"🍝 Spaghetti is cooking at http://{s.host}:{s.port}  (engine: {engine.name})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 Kitchen closed.")


if __name__ == "__main__":
    main()
