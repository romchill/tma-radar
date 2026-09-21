#!/bin/sh
# Публичный HTTPS-адрес для мини-аппа.
#
# Serveo, а не localhost.run и не Pinggy:
#   * Pinggy показывает страницу-предупреждение — вебвью Telegram на ней
#     спотыкается и отдаёт белый экран;
#   * localhost.run рвал соединение каждые несколько минут, и каждая смена
#     адреса делала все кнопки в старых сообщениях нерабочими;
#   * Serveo без заглушки и умеет закреплять поддомен за ssh-ключом.
#
# Если ключ зарегистрирован на console.serveo.net и задан TUNNEL_SUBDOMAIN,
# адрес становится постоянным — тогда кнопки не протухают вообще никогда.
#
# Выданный адрес пишется в /shared/tunnel_url, оттуда его читает бот.
set -u

: "${TUNNEL_TARGET_HOST:=api}"
: "${TUNNEL_TARGET_PORT:=8000}"
: "${TUNNEL_SUBDOMAIN:=}"
# Serveo рвёт сеанс примерно каждые 50 секунд — это его норма, а не авария.
# Раньше скрипт считал короткий сеанс неудачей и удваивал паузу до 10 минут,
# так что приложение лежало почти всё время. Теперь удачей считается сам факт
# выданного адреса, и после разрыва туннель поднимается за пару секунд.
: "${TUNNEL_RETRY_MIN:=3}"
: "${TUNNEL_RETRY_MAX:=60}"
: "${TUNNEL_OK_FLAG:=/tmp/tunnel_connected}"
: "${TUNNEL_URL_FILE:=/shared/tunnel_url}"
: "${TUNNEL_KEY:=/shared/ssh/id_ed25519}"

mkdir -p "$(dirname "$TUNNEL_URL_FILE")" /shared/ssh

# Ключ нужен, чтобы закрепить поддомен. Создаётся один раз и живёт в томе.
if [ ! -f "$TUNNEL_KEY" ]; then
	ssh-keygen -t ed25519 -N "" -C tma-radar -f "$TUNNEL_KEY" >/dev/null 2>&1
	echo "создан ssh-ключ для туннеля"
fi
chmod 600 "$TUNNEL_KEY" 2>/dev/null

if [ -n "$TUNNEL_SUBDOMAIN" ]; then
	FORWARD="${TUNNEL_SUBDOMAIN}:80:${TUNNEL_TARGET_HOST}:${TUNNEL_TARGET_PORT}"
	echo "прошу постоянный адрес: ${TUNNEL_SUBDOMAIN}.serveo.net"
else
	FORWARD="80:${TUNNEL_TARGET_HOST}:${TUNNEL_TARGET_PORT}"
	echo "постоянный адрес не задан — будет временный"
fi

delay=$TUNNEL_RETRY_MIN

while true; do
	started=$(date +%s)
	rm -f "$TUNNEL_OK_FLAG"

	ssh -n -T \
		-i "$TUNNEL_KEY" \
		-o IdentitiesOnly=yes \
		-o StrictHostKeyChecking=no \
		-o UserKnownHostsFile=/dev/null \
		-o ServerAliveInterval=30 \
		-o ServerAliveCountMax=3 \
		-o ExitOnForwardFailure=yes \
		-R "$FORWARD" serveo.net 2>&1 |
		while IFS= read -r line; do
			clean=$(printf '%s' "$line" | sed 's/\x1b\[[0-9;]*m//g')
			echo "$clean"

			# Адрес берём ТОЛЬКО из строки «Forwarding HTTP traffic from …».
			# Serveo подмешивает в вывод рекламу со ссылкой на console.serveo.net,
			# и без этой привязки она затирала настоящий адрес приложения.
			case "$clean" in
			*"Forwarding HTTP traffic from"*)
				url=$(printf '%s' "$clean" | grep -oE 'https://[a-zA-Z0-9.-]+' | head -1)
				if [ -n "$url" ]; then
					echo "адрес: $url"
					printf '%s' "$url" > "$TUNNEL_URL_FILE"
					# цикл чтения крутится в подоболочке, наружу
					# сигнал передаётся файлом
					: > "$TUNNEL_OK_FLAG"
				fi
				;;
			esac
		done

	lived=$(( $(date +%s) - started ))

	if [ -f "$TUNNEL_OK_FLAG" ]; then
		# адрес выдавался — связь рабочая, поднимаемся сразу
		echo "сеанс прожил $lived с"
		delay=$TUNNEL_RETRY_MIN
	else
		# адреса не было вовсе: serveo лежит или не пускает — не долбимся
		echo "сеанс прожил $lived с, адрес так и не выдан"
		delay=$(( delay * 2 ))
		[ "$delay" -gt "$TUNNEL_RETRY_MAX" ] && delay=$TUNNEL_RETRY_MAX
	fi

	echo "переподключаюсь через $delay секунд"
	sleep "$delay"
done
