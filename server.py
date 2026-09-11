import asyncio
import websockets
import json
import os

# Bağlı istemcileri ve açık anahtarlarını saklayan sözlük
CLIENTS = {}

async def handler(websocket):
    username = None
    try:
        # 1. Bağlantı ilk kurulduğunda kayıt bilgisini al
        init_data_raw = await websocket.recv()
        init_data = json.loads(init_data_raw)
        
        username = init_data.get("username")
        public_key = init_data.get("public_key")
        
        if username:
            CLIENTS[username] = {
                "ws": websocket,
                "public_key": public_key
            }
            print(f"[+] '{username}' sunucuya başarıyla bağlandı.")

        # 2. İstemciden gelen mesajları dinle
        async for message in websocket:
            msg_obj = json.loads(message)
            msg_type = msg_obj.get("type")

            # Kullanıcı başka birinin Public Key'ini istediğinde
            if msg_type == "get_key":
                target = msg_obj.get("target")
                if target in CLIENTS:
                    res = json.dumps({
                        "type": "key_response",
                        "username": target,
                        "public_key": CLIENTS[target]["public_key"]
                    })
                    await websocket.send(res)
                else:
                    res = json.dumps({
                        "type": "error",
                        "message": f"'{target}' adında bir kullanıcı bulunamadı."
                    })
                    await websocket.send(res)

            # Şifrelenmiş mesajı hedef kişiye ilet
            elif msg_type == "msg":
                target = msg_obj.get("target")
                if target in CLIENTS:
                    await CLIENTS[target]["ws"].send(message)

    except websockets.exceptions.ConnectionClosed:
        pass
    except Exception as e:
        print(f"[-] Hata ({username}): {e}")
    finally:
        if username and username in CLIENTS:
            del CLIENTS[username]
            print(f"[-] '{username}' ayrıldı.")

async def main():
    # Render'ın atadığı portu al
    port = int(os.environ.get("PORT", 10000))
    print(f"=== GİZLİ REHBER WEBSOCKET SUNUCUSU BAŞLATILIYOR (PORT {port}) ===")
    
    async with websockets.serve(handler, "0.0.0.0", port):
        await asyncio.Future()  # Sunucuyu sürekli açık tutar

if __name__ == "__main__":
    asyncio.run(main())