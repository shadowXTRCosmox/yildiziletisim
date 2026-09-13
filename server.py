import asyncio
import json
import websockets

connected_clients = {}  # username: {"ws": ws, "public_key": pub, "color": color, "avatar": avatar, "bio": bio}
friendships = {}      # username: set of friends
friend_requests = {}  # username: set of pending requests from others

async def register_user(ws, data):
    username = data.get("username")
    password = data.get("password")
    public_key = data.get("public_key")
    color = data.get("color", "#89b4fa")
    avatar = data.get("avatar", "")
    bio = data.get("bio", "")

    if not username or not password or not public_key:
        await ws.send(json.dumps({"type": "error", "message": "Eksik bilgi!"}))
        return False

    db = load_users_db()
    if username in db:
        await ws.send(json.dumps({"type": "error", "message": "Bu kullanıcı adı zaten alınmış!"}))
        return False

    db[username] = {
        "password": password,
        "public_key": public_key,
        "color": color,
        "avatar": avatar,
        "bio": bio
    }
    save_users_db(db)
    
    await ws.send(json.dumps({"type": "status", "status": "success", "message": "Kayıt başarılı!"}))
    return True

async def login_user(ws, data):
    username = data.get("username")
    password = data.get("password")

    db = load_users_db()
    if username not in db or db[username]["password"] != password:
        await ws.send(json.dumps({"type": "status", "status": "error", "message": "Geçersiz kullanıcı adı veya şifre!"}))
        return None

    connected_clients[username] = {
        "ws": ws,
        "public_key": db[username]["public_key"],
        "color": data.get("color", db[username].get("color", "#89b4fa")),
        "avatar": data.get("avatar", db[username].get("avatar", "")),
        "bio": db[username].get("bio", "")
    }
    
    db[username]["color"] = connected_clients[username]["color"]
    db[username]["avatar"] = connected_clients[username]["avatar"]
    save_users_db(db)

    await ws.send(json.dumps({"type": "status", "status": "success"}))
    return username

def load_users_db():
    try:
        with open("users_db.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_users_db(db):
    try:
        with open("users_db.json", "w", encoding="utf-8") as f:
            json.dump(db, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"[-] DB kayıt hatası: {e}")

async def broadcast_user_list():
    users = list(connected_clients.keys())
    avatars = {u: data["avatar"] for u, data in connected_clients.items()}
    colors = {u: data["color"] for u, data in connected_clients.items()}
    bios = {u: data["bio"] for u, data in connected_clients.items()}

    for username, client in list(connected_clients.items()):
        ws = client["ws"]
        user_friends = list(friendships.get(username, []))
        user_requests = list(friend_requests.get(username, []))
        
        payload = json.dumps({
            "type": "user_list_update",
            "users": users,
            "friends": user_friends,
            "requests": user_requests,
            "avatars": avatars,
            "colors": colors,
            "bios": bios
        })
        try:
            await ws.send(payload)
        except Exception:
            pass

async def handle_client(ws):
    current_user = None
    try:
        async for message in ws:
            data = json.loads(message)
            msg_type = data.get("type")

            if msg_type == "register":
                await register_user(ws, data)
            elif msg_type == "login":
                user = await login_user(ws, data)
                if user:
                    current_user = user
                    if current_user not in friendships:
                        friendships[current_user] = set()
                    if current_user not in friend_requests:
                        friend_requests[current_user] = set()
                    await broadcast_user_list()
            elif msg_type == "get_users":
                if current_user:
                    await broadcast_user_list()
            elif msg_type == "get_key":
                target = data.get("target")
                if target in connected_clients:
                    await ws.send(json.dumps({
                        "type": "key_response",
                        "username": target,
                        "public_key": connected_clients[target]["public_key"]
                    }))
            elif msg_type == "msg":
                target = data.get("target")
                if target in connected_clients:
                    target_ws = connected_clients[target]["ws"]
                    await target_ws.send(message)
            elif msg_type == "update_profile":
                if current_user:
                    bio = data.get("bio", "")
                    avatar = data.get("avatar", "")
                    color = data.get("color", "#89b4fa")
                    
                    connected_clients[current_user]["bio"] = bio
                    connected_clients[current_user]["avatar"] = avatar
                    connected_clients[current_user]["color"] = color
                    
                    db = load_users_db()
                    if current_user in db:
                        db[current_user]["bio"] = bio
                        db[current_user]["avatar"] = avatar
                        db[current_user]["color"] = color
                        save_users_db(db)
                        
                    await broadcast_user_list()
            elif msg_type == "friend_request":
                target = data.get("target")
                if current_user and target and target in load_users_db():
                    if target not in friend_requests:
                        friend_requests[target] = set()
                    friend_requests[target].add(current_user)
                    
                    if target in connected_clients:
                        await connected_clients[target]["ws"].send(json.dumps({
                            "type": "friend_request_received",
                            "sender": current_user
                        }))
                    await broadcast_user_list()
            elif msg_type == "accept_friend":
                sender = data.get("sender")
                if current_user and sender:
                    if current_user in friend_requests and sender in friend_requests[current_user]:
                        friend_requests[current_user].remove(sender)
                    
                    if current_user not in friendships:
                        friendships[current_user] = set()
                    if sender not in friendships:
                        friendships[sender] = set()
                        
                    friendships[current_user].add(sender)
                    friendships[sender].add(current_user)
                    await broadcast_user_list()
            elif msg_type == "reject_friend":
                sender = data.get("sender")
                if current_user and sender:
                    if current_user in friend_requests and sender in friend_requests[current_user]:
                        friend_requests[current_user].remove(sender)
                    await broadcast_user_list()

    except Exception as e:
        print(f"[-] Hata: {e}")
    finally:
        if current_user and current_user in connected_clients:
            del connected_clients[current_user]
            await broadcast_user_list()

async def main():
    async with websockets.serve(handle_client, "0.0.0.0", 10000):
        print("[*] WebSocket sunucusu başlatıldı...")
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
