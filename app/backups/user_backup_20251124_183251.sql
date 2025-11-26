-- MySQL dump 10.13  Distrib 8.0.43, for Win64 (x86_64)
--
-- Host: localhost    Database: c_insight_db
-- ------------------------------------------------------
-- Server version	8.0.43

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!50503 SET NAMES utf8mb4 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;

--
-- Table structure for table `users`
--

DROP TABLE IF EXISTS `users`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `users` (
  `id` int NOT NULL AUTO_INCREMENT,
  `username` varchar(50) NOT NULL,
  `password` varchar(255) NOT NULL,
  `first_name` varchar(100) NOT NULL,
  `last_name` varchar(100) NOT NULL,
  `role` enum('student','teacher','admin') NOT NULL,
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  `email` varchar(150) DEFAULT NULL,
  `google_id` varchar(200) DEFAULT NULL,
  `profile_pic` varchar(300) DEFAULT NULL,
  `provider` varchar(50) DEFAULT 'local',
  `provider_id` varchar(150) DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `username` (`username`),
  UNIQUE KEY `email` (`email`),
  UNIQUE KEY `google_id` (`google_id`)
) ENGINE=InnoDB AUTO_INCREMENT=125 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `users`
--
-- WHERE:  role != "admin"

LOCK TABLES `users` WRITE;
/*!40000 ALTER TABLE `users` DISABLE KEYS */;
INSERT INTO `users` VALUES (113,'Vins','scrypt:32768:8:1$UZkx1erEQUOFD8Wc$3652cfb1e7e1b6cef1d3635fd976712d1d4af5848882f68bfab93d18e124857254d58d87e9bc0b4f56affba468e12e7b26e5e4cb242dc7c1917691674ea6d261','Vincent','Villas','teacher','2025-10-22 01:27:40',NULL,NULL,NULL,'local',NULL),(119,'Zac','scrypt:32768:8:1$FBOzvJZ0p0HXz4K3$184266aa414106c9e24246fa76abad2967e65da522a806c8f0a76edcac2b9561c7863d30a491f6591a26311a08ce5bfe7f6afb366c5f020c3f0f7c187a895b61','Zachary','Maristela','student','2025-11-04 23:54:14',NULL,NULL,NULL,'local',NULL),(120,'Joey','scrypt:32768:8:1$7gxJGBkJ6JKJzpA1$2cb40784ef72f5a26f15c3b246893aa5b5e362491f407ca99834c482bd49cfc0fddb432dbf6a83c44687059ac7a6f5ae17a513cb58c1442060ab4d01a9faf786','Joey','Hemp','student','2025-11-13 08:38:39',NULL,NULL,NULL,'local',NULL),(123,'John','scrypt:32768:8:1$d8VUNOjTApasxG0h$03620370dd62b26aea8dcc055266b2ffd3d560da6340e47535c3d121941a0b1317573b50cd3c805c590ed03d21d8a870379f4947194a3f07240221db03828592','John','Doe','student','2025-11-21 10:03:14','john@gmail.com',NULL,NULL,'local',NULL);
/*!40000 ALTER TABLE `users` ENABLE KEYS */;
UNLOCK TABLES;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

-- Dump completed on 2025-11-24 18:32:53
