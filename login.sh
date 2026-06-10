# Для перезагрузки сервера 
docker-compose down
docker-compose up --build -d


# Если упадет интернет на сервере
ping 64.0.0.0 -c 2 -w2 || wget -qO - "login.telecom.mipt.ru/bin/login.cgi?login=1436083&memorize=on&password=`((wget login.telecom.mipt.ru/bin/getqc.cgi -qO -; echo -n 395065) | md5sum - | head -c32 )`"


# Всякие логи

docker-compose logs -f
docker-compose ps


